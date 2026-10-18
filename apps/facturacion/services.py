"""Emisión de facturas electrónicas: de transacción exitosa a documento aprobado.

El recorrido de cada factura:

1. ``registrar_factura`` la crea ``PENDIENTE`` (con su número legal y el documento ya
   armado) dentro de la misma transacción de base de datos en la que la operación pasa a
   ``EXITOSA``: o quedan las dos o no queda ninguna, y una operación no puede tener dos
   facturas.
2. Cuando esa transacción de base de datos se confirma, ``enviar`` se la manda al
   proveedor. **Nunca revierte ni toca la operación**: si el proveedor no está disponible
   o contesta con error, la factura sigue ``PENDIENTE`` con el motivo y la hora del
   próximo reintento (espera creciente, de 1 a 60 minutos).
3. En cuanto una factura queda ``EMITIDA``, ``enviar_por_correo`` se la manda al correo del
   cliente con el PDF adjunto. Si el correo falla, la factura sigue emitida con el motivo
   en ``correo_error`` y se reintenta.
4. ``procesar_pendientes`` (el comando ``manage.py procesar_facturas``, para correr cada
   pocos minutos) reintenta las pendientes, consulta a SIFEN las ``ENVIADA`` hasta que
   queden ``EMITIDA`` o ``RECHAZADA`` y reenvía los correos que no salieron. También crea
   la factura de las operaciones exitosas que no la tengan.

Los montos van en guaraníes enteros (el guaraní no tiene centavos).
"""

import logging
import re
from datetime import datetime, timedelta
from datetime import timezone as zona
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from apps.banco.services import formatear_guaranies
from apps.transacciones.models import MetodoPago, Transaccion

from .models import Factura, SecuenciaFactura
from .proveedores import NOMBRE_SIMULADO, ErrorFacturacion, obtener_proveedor

logger = logging.getLogger(__name__)

#: Paraguay tiene hora fija UTC-3 desde octubre de 2024 (SIFEN pide la hora local).
HORA_DE_PARAGUAY = zona(timedelta(hours=-3))

#: Espera máxima entre dos reintentos de envío.
MINUTOS_MAXIMOS_ENTRE_REINTENTOS = 60

# Tipo de pago de SIFEN según el método de pago de la operación.
TIPO_DE_PAGO_SIFEN = {
    MetodoPago.TIPO_EFECTIVO: '1',
    MetodoPago.TIPO_TARJETA_CREDITO: '3',
    MetodoPago.TIPO_TRANSFERENCIA: '5',
    MetodoPago.TIPO_BILLETERA: '7',
}
TIPO_DE_PAGO_OTRO = '99'


def _guaranies_enteros(monto):
    return int(Decimal(monto).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _separar_ruc(documento):
    """``('80012345', '6')`` si el documento tiene forma de RUC (``número-dígito``);
    ``None`` si es una cédula u otro documento."""
    coincide = re.fullmatch(r'(\d+)-(\d)', documento.strip())
    return coincide.groups() if coincide else None


def _concepto(transaccion):
    """Descripción del ítem facturado (SIFEN admite hasta 120 caracteres)."""
    if transaccion.tipo == 'CAMBIO':
        texto = (
            f'Cambio de {transaccion.cantidad:.2f} {transaccion.moneda.codigo} a '
            f'{transaccion.cantidad_destino:.2f} {transaccion.moneda_destino.codigo}'
        )
    else:
        verbo = 'Compra' if transaccion.tipo == 'COMPRA' else 'Venta'
        texto = f'{verbo} de {transaccion.cantidad:.2f} {transaccion.moneda.codigo}'
    return f'{texto} (operación #{transaccion.pk})'[:120]


def _informacion_adicional(transaccion):
    """Texto que SIFEN imprime en el documento: la tasa aplicada y la comisión."""
    if transaccion.tipo == 'CAMBIO':
        tasas = (
            f'1 {transaccion.moneda.codigo} = {transaccion.tasa_cambio:.2f} Gs; '
            f'1 {transaccion.moneda_destino.codigo} = {transaccion.tasa_cambio_destino:.2f} Gs'
        )
    else:
        tasas = f'1 {transaccion.moneda.codigo} = {transaccion.tasa_cambio:.2f} Gs'
    return (
        f'Tasa aplicada: {tasas}. Comisión {transaccion.comision_porcentaje}% '
        f'({_guaranies_enteros(transaccion.monto_comision)} Gs).'
    )


def construir_documento(transaccion, numero, emitida_en):
    """El documento electrónico resumido (``JSON_RESUMIDO_DE`` de Factura Segura) de esta
    operación: una factura de contado, en guaraníes, con un solo ítem por el total.

    El receptor es el cliente: con RUC (``número-dígito``) es contribuyente; con cédula,
    no. Su correo es el del usuario que operó (Factura Segura lo exige). La operación se
    factura como exenta de IVA.
    """
    emisor = settings.FACTURACION_EMISOR
    cliente = transaccion.cliente
    juridica = cliente.tipo == 'JURIDICA'
    ruc = _separar_ruc(cliente.documento)
    total = _guaranies_enteros(transaccion.monto_total)

    receptor = {
        'iNatRec': '1' if ruc else '2',
        'iTiOpe': '1' if juridica else '2',
        'cPaisRec': 'PRY',
        'iTiContRec': '2' if juridica else '1',
    }
    if ruc:
        receptor.update({'dRucRec': ruc[0], 'dDVRec': ruc[1], 'iTipIDRec': '0', 'dNumIDRec': '0'})
    else:
        receptor.update({'iTipIDRec': '1', 'dNumIDRec': cliente.documento.strip()})
    receptor.update({
        'dNomRec': (cliente.razon_social or cliente.nombre)[:255],
        'dEmailRec': transaccion.usuario.email,
    })

    pago = {
        'iTiPago': TIPO_DE_PAGO_SIFEN.get(transaccion.metodo_pago.tipo, TIPO_DE_PAGO_OTRO),
        'dMonTiPag': str(total),
        'cMoneTiPag': 'PYG',
        'dTiCamTiPag': '1',
    }
    if transaccion.metodo_pago.tipo == MetodoPago.TIPO_TARJETA_CREDITO:
        pago.update({'iDenTarj': '99', 'dDesDenTarj': 'Tarjeta de crédito', 'iForProPa': '2'})

    return {
        'iTipEmi': '1',
        'iTiDE': '1',
        'dNumTim': settings.FACTURACION_TIMBRADO,
        'dFeIniT': settings.FACTURACION_TIMBRADO_INICIO,
        'dEst': settings.FACTURACION_ESTABLECIMIENTO,
        'dPunExp': settings.FACTURACION_PUNTO_EXPEDICION,
        'dNumDoc': f'{numero:07d}',
        'dFeEmiDE': emitida_en.astimezone(HORA_DE_PARAGUAY).strftime('%Y-%m-%dT%H:%M:%S'),
        'iTipTra': '2',
        'iTImp': '1',
        'cMoneOpe': 'PYG',
        'dCondTiCam': '1',
        'dTiCam': '1',
        'dRucEm': emisor['ruc'],
        'dDVEmi': emisor['dv'],
        'iTipCont': '2',
        'dNomEmi': emisor['nombre'],
        'dDirEmi': emisor['direccion'],
        'dNumCas': emisor['numero_casa'],
        'cDepEmi': emisor['departamento_codigo'],
        'dDesDepEmi': emisor['departamento'],
        'cCiuEmi': emisor['ciudad_codigo'],
        'dDesCiuEmi': emisor['ciudad'],
        'dTelEmi': emisor['telefono'],
        'dEmailE': emisor['email'],
        'gActEco': [{'cActEco': emisor['actividad_codigo'], 'dDesActEco': emisor['actividad']}],
        **receptor,
        'iIndPres': '1' if transaccion.modalidad == 'PRESENCIAL' else '2',
        'iCondOpe': '1',
        'gPaConEIni': [pago],
        'iCondCred': '1',
        'dPlazoCre': '0',
        'gCamItem': [{
            'dCodInt': f'TX-{transaccion.pk}',
            'dDesProSer': _concepto(transaccion),
            'cUniMed': '77',
            'dCantProSer': '1',
            'dPUniProSer': str(total),
            'dDescItem': '0',
            'dDescGloItem': '0',
            'dAntPreUniIt': '0',
            'dAntGloPreUniIt': '0',
            'iAfecIVA': '3',
            'dPropIVA': '0',
            'dTasaIVA': '0',
        }],
        'CDC': '0',
        'dCodSeg': '0',
        'dDVId': '0',
        'dSisFact': '1',
        'dInfAdic': _informacion_adicional(transaccion),
    }


def registrar_factura(transaccion):
    """Crea la factura ``PENDIENTE`` de una operación exitosa y programa su envío para
    cuando se confirme la transacción de base de datos. Devuelve ``(factura, creada)``.

    Es idempotente: si la operación ya tiene factura la devuelve sin crear otra. Debe
    llamarse dentro de la transacción en la que la operación pasa a ``EXITOSA``.
    """
    existente = Factura.objects.filter(transaccion=transaccion).first()
    if existente is not None:
        return existente, False

    establecimiento = settings.FACTURACION_ESTABLECIMIENTO
    punto = settings.FACTURACION_PUNTO_EXPEDICION
    numero = SecuenciaFactura.siguiente(establecimiento, punto)
    emitida_en = timezone.now()
    factura = Factura.objects.create(
        transaccion=transaccion,
        establecimiento=establecimiento,
        punto_expedicion=punto,
        numero=numero,
        timbrado=settings.FACTURACION_TIMBRADO,
        monto=transaccion.monto_total,
        fecha_emision=emitida_en,
        payload=construir_documento(transaccion, numero, emitida_en),
    )
    transaction.on_commit(lambda: enviar(factura.pk))
    return factura, True


def _siguiente_intento(intentos, ahora):
    """Espera creciente entre reintentos: 1, 2, 4, 8... minutos, hasta una hora."""
    minutos = min(2 ** max(intentos - 1, 0), MINUTOS_MAXIMOS_ENTRE_REINTENTOS)
    return ahora + timedelta(minutes=minutos)


def estado_desde_sifen(estado_sifen):
    """El estado de la factura que corresponde a lo que SIFEN informa del documento."""
    estado = (estado_sifen or '').strip().lower()
    if estado in ('aprobado', 'aprobado con observación', 'aprobado con observacion'):
        return Factura.EMITIDA
    if estado == 'rechazado':
        return Factura.RECHAZADA
    return Factura.ENVIADA  # solicitada o enviada: SIFEN todavía no resolvió


def _aplicar_respuesta(factura, respuesta, proveedor):
    factura.proveedor = proveedor.nombre
    factura.cdc = respuesta.cdc or factura.cdc
    factura.estado = estado_desde_sifen(respuesta.estado_sifen)
    factura.estado_sifen = (respuesta.descripcion or respuesta.estado_sifen)[:255]
    factura.respuesta = respuesta.datos
    factura.proximo_intento = None
    factura.ultimo_error = (
        factura.estado_sifen if factura.estado == Factura.RECHAZADA else ''
    )


def _registrar_fallo(factura, motivo, ahora):
    factura.intentos += 1
    factura.ultimo_error = motivo[:255]
    factura.proximo_intento = _siguiente_intento(factura.intentos, ahora)


def enviar(factura_id, ahora=None):
    """Envía al proveedor una factura ``PENDIENTE``. Devuelve la factura, o ``None`` si
    ya no estaba pendiente o la está procesando otro proceso.

    **Nunca lanza ni toca la operación**: cualquier fallo queda anotado en la factura
    (``ultimo_error``) con la hora del próximo reintento.
    """
    ahora = ahora or timezone.now()
    with transaction.atomic():
        factura = (
            Factura.objects.select_for_update(skip_locked=True)
            .filter(pk=factura_id, estado=Factura.PENDIENTE).first()
        )
        if factura is None:
            return None
        try:
            proveedor = obtener_proveedor()
            respuesta = proveedor.emitir(factura.payload)
        except ErrorFacturacion as exc:
            logger.warning('No se pudo enviar la factura %s: %s', factura.pk, exc)
            _registrar_fallo(factura, str(exc), ahora)
        except Exception:  # un fallo del proveedor nunca puede romper el pago
            logger.exception('Error inesperado al enviar la factura %s', factura.pk)
            _registrar_fallo(factura, 'Error inesperado al enviar la factura.', ahora)
        else:
            _aplicar_respuesta(factura, respuesta, proveedor)
        factura.save()
    if factura.estado == Factura.EMITIDA:
        enviar_por_correo(factura.pk)
    return factura


def _armar_correo(factura, destinatario):
    """El correo con la factura: un texto corto y el PDF adjunto."""
    from .pdf import generar_pdf  # import diferido: el PDF usa constantes de este módulo

    concepto = factura.payload['gCamItem'][0]['dDesProSer']
    lineas = [
        f"Hola {factura.payload['dNomRec']},",
        '',
        f'Te enviamos tu factura electrónica N° {factura.numero_legal} por: {concepto}.',
        f'Total: {formatear_guaranies(factura.monto)}.',
        '',
        'También podés verla y descargarla cuando quieras desde la sección Facturas del '
        'portal de GlobalExchange.',
    ]
    if factura.proveedor == NOMBRE_SIMULADO:
        lineas += [
            '',
            'Este es un documento de prueba generado por el simulador: no tiene validez '
            'tributaria.',
        ]
    lineas += ['', 'GlobalExchange']
    mensaje = EmailMessage(
        subject=f'Factura electrónica {factura.numero_legal} - GlobalExchange',
        body='\n'.join(lineas),
        to=[destinatario],
    )
    mensaje.attach(f'factura-{factura.numero_legal}.pdf', generar_pdf(factura), 'application/pdf')
    return mensaje


def enviar_por_correo(factura_id):
    """Manda una factura ``EMITIDA`` al correo del cliente (el del usuario que hizo la
    operación, que viaja en el documento) con el PDF adjunto. Devuelve True si salió.

    Se manda una sola vez (``correo_enviado_en``). **Nunca lanza**: si el correo falla
    queda anotado en ``correo_error`` y ``procesar_pendientes`` lo reintenta; la factura
    sigue emitida. Con ``FACTURACION_ENVIAR_CORREO=False`` no hace nada.
    """
    if not settings.FACTURACION_ENVIAR_CORREO:
        return False
    with transaction.atomic():
        factura = (
            Factura.objects.select_for_update(skip_locked=True, of=('self',))
            .filter(pk=factura_id, estado=Factura.EMITIDA, correo_enviado_en__isnull=True)
            .first()
        )
        if factura is None:
            return False
        destinatario = factura.payload.get('dEmailRec')
        if not destinatario:
            return False
        try:
            _armar_correo(factura, destinatario).send()
        except Exception as exc:  # un correo caído no puede afectar a la factura
            logger.warning('No se pudo mandar por correo la factura %s: %s', factura.pk, exc)
            factura.correo_error = f'No se pudo mandar el correo: {exc}'[:255]
            factura.save(update_fields=['correo_error'])
            return False
        factura.correo_enviado_en = timezone.now()
        factura.correo_error = ''
        factura.save(update_fields=['correo_enviado_en', 'correo_error'])
    return True


def consultar_estado(factura_id):
    """Pregunta a SIFEN (por el proveedor) cómo quedó una factura ``ENVIADA``. Si no se
    puede consultar, anota el motivo y la deja como está. Devuelve la factura o
    ``None`` si ya no estaba enviada."""
    with transaction.atomic():
        factura = (
            Factura.objects.select_for_update(skip_locked=True)
            .filter(pk=factura_id, estado=Factura.ENVIADA).first()
        )
        if factura is None:
            return None
        try:
            proveedor = obtener_proveedor()
            respuesta = proveedor.consultar(factura.cdc)
        except ErrorFacturacion as exc:
            logger.warning('No se pudo consultar la factura %s: %s', factura.pk, exc)
            factura.ultimo_error = str(exc)[:255]
        except Exception:
            logger.exception('Error inesperado al consultar la factura %s', factura.pk)
            factura.ultimo_error = 'Error inesperado al consultar la factura.'
        else:
            _aplicar_respuesta(factura, respuesta, proveedor)
        factura.save()
    if factura.estado == Factura.EMITIDA:
        enviar_por_correo(factura.pk)
    return factura


def procesar_pendientes(ahora=None):
    """Pone al día todas las facturas. Devuelve cuántas hizo de cada cosa::

        {'registradas': ..., 'enviadas': ..., 'consultadas': ..., 'correos': ...}

    1. Crea la factura de las operaciones exitosas que no la tengan.
    2. Reintenta las ``PENDIENTE`` cuya hora de reintento ya llegó.
    3. Consulta a SIFEN las ``ENVIADA``.
    4. Manda por correo las ``EMITIDA`` cuyo correo todavía no salió (``correos`` cuenta
       solo estos reenvíos: los correos que salen en los pasos anteriores no se suman).
    """
    ahora = ahora or timezone.now()
    resumen = {'registradas': 0, 'enviadas': 0, 'consultadas': 0, 'correos': 0}

    for operacion in Transaccion.objects.filter(estado='EXITOSA', factura__isnull=True):
        with transaction.atomic():
            _, creada = registrar_factura(operacion)
        resumen['registradas'] += creada

    pendientes = Factura.objects.filter(estado=Factura.PENDIENTE).exclude(
        proximo_intento__gt=ahora
    ).values_list('pk', flat=True)
    for pk in list(pendientes):
        factura = enviar(pk, ahora)
        resumen['enviadas'] += factura is not None and factura.estado != Factura.PENDIENTE

    for pk in list(Factura.objects.filter(estado=Factura.ENVIADA).values_list('pk', flat=True)):
        resumen['consultadas'] += consultar_estado(pk) is not None

    if settings.FACTURACION_ENVIAR_CORREO:
        sin_correo = Factura.objects.filter(
            estado=Factura.EMITIDA, correo_enviado_en__isnull=True
        ).values_list('pk', flat=True)
        for pk in list(sin_correo):
            resumen['correos'] += enviar_por_correo(pk)

    return resumen
