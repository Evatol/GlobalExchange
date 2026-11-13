"""Emisión de facturas electrónicas: de transacción exitosa a documento aprobado
(``apps.facturacion.services`` tiene la consulta y el PDF).

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
4. Cuando se anula una operación en efectivo que tenía factura, ``anular_factura`` anula
   la factura y emite su ``NotaCredito`` por el total (E4-191), que sigue el mismo
   recorrido de envío, reintento y consulta que la factura. Cada emisión, descarga y
   anulación queda en el registro de auditoría (``EventoFactura``).
5. ``procesar_pendientes`` (el comando ``manage.py procesar_facturas``, para correr cada
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
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from apps.banco.services import formatear_guaranies
from apps.transacciones.models import MetodoPago, Transaccion

from .models import EventoFactura, Factura, NotaCredito, SecuenciaFactura
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
        'iIndPres': '1' if transaccion.modalidad in ('PRESENCIAL', 'TERMINAL') else '2',
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
        estado=Factura.PENDIENTE,
        establecimiento=establecimiento,
        punto_expedicion=punto,
        correlativo=numero,
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


def _aplicar_respuesta(documento, respuesta, proveedor):
    """Aplica lo que contestó el proveedor a una factura o a una nota de crédito. La
    primera vez que queda emitida, deja constancia en la auditoría."""
    estaba_emitida = documento.estado == Factura.EMITIDA
    documento.proveedor = proveedor.nombre
    documento.cdc = respuesta.cdc or documento.cdc
    documento.estado = estado_desde_sifen(respuesta.estado_sifen)
    documento.estado_sifen = (respuesta.descripcion or respuesta.estado_sifen)[:255]
    documento.respuesta = respuesta.datos
    documento.proximo_intento = None
    documento.ultimo_error = (
        documento.estado_sifen if documento.estado == Factura.RECHAZADA else ''
    )
    if documento.estado == Factura.EMITIDA and not estaba_emitida:
        if isinstance(documento, NotaCredito):
            EventoFactura.registrar(
                documento.factura, EventoFactura.NOTA_CREDITO,
                detalle=f'Nota de crédito {documento.numero} emitida (CDC {documento.cdc})',
            )
        else:
            EventoFactura.registrar(
                documento, EventoFactura.EMISION, detalle=f'Emitida (CDC {documento.cdc})',
            )


def _registrar_fallo(documento, motivo, ahora):
    documento.intentos += 1
    documento.ultimo_error = motivo[:255]
    documento.proximo_intento = _siguiente_intento(documento.intentos, ahora)


def _enviar(modelo, documento_id, ahora):
    """Envía al proveedor una factura o una nota de crédito ``PENDIENTE``. Devuelve el
    documento, o ``None`` si ya no estaba pendiente o lo está procesando otro proceso.
    Nunca lanza: cualquier fallo queda anotado en el documento con la hora del próximo
    reintento."""
    with transaction.atomic():
        documento = (
            modelo.objects.select_for_update(skip_locked=True)
            .filter(pk=documento_id, estado=Factura.PENDIENTE).first()
        )
        if documento is None:
            return None
        try:
            proveedor = obtener_proveedor()
            respuesta = proveedor.emitir(documento.payload)
        except ErrorFacturacion as exc:
            logger.warning('No se pudo enviar %s %s: %s', modelo.__name__, documento.pk, exc)
            _registrar_fallo(documento, str(exc), ahora)
        except Exception:  # un fallo del proveedor nunca puede romper el pago
            logger.exception('Error inesperado al enviar %s %s', modelo.__name__, documento.pk)
            _registrar_fallo(documento, 'Error inesperado al enviar el documento.', ahora)
        else:
            _aplicar_respuesta(documento, respuesta, proveedor)
        documento.save()
    return documento


def enviar(factura_id, ahora=None, correo=True):
    """Envía al proveedor una factura ``PENDIENTE``. Devuelve la factura, o ``None`` si
    ya no estaba pendiente o la está procesando otro proceso.

    **Nunca lanza ni toca la operación**: cualquier fallo queda anotado en la factura
    (``ultimo_error``) con la hora del próximo reintento. Si queda emitida, se manda por
    correo salvo con ``correo=False`` (lo usa la carga de datos de demostración, para no
    escribirle a clientes de mentira).
    """
    factura = _enviar(Factura, factura_id, ahora or timezone.now())
    if factura is not None and factura.estado == Factura.EMITIDA and correo:
        enviar_por_correo(factura.pk)
    return factura


def enviar_nota(nota_id, ahora=None):
    """Envía al proveedor una nota de crédito ``PENDIENTE``, con las mismas garantías que
    ``enviar``: nunca lanza y se reintenta si falla."""
    return _enviar(NotaCredito, nota_id, ahora or timezone.now())


# Lo de una factura que no va en la nota de crédito que la anula: la condición de pago y
# el indicador de presencia son de la venta, no de la devolución.
CAMPOS_SOLO_DE_FACTURA = ('iIndPres', 'iCondOpe', 'gPaConEIni', 'iCondCred', 'dPlazoCre')
#: Motivo de emisión de la nota de crédito en SIFEN: devolución.
MOTIVO_DE_LA_NOTA = '2'


def construir_nota_credito(factura, numero, emitida_en):
    """El documento electrónico de la nota de crédito que anula ``factura``: el mismo
    emisor, receptor e ítems que la factura (por el total), el tipo de documento 5, su
    propio número y la referencia al CDC de la factura (``gCamDEAsoc``). Una factura sin
    documento guardado (las de demostración) se reconstruye desde su operación."""
    base = factura.payload or construir_documento(
        factura.transaccion, factura.correlativo or factura.pk, factura.fecha_emision or emitida_en
    )
    documento = {k: v for k, v in base.items() if k not in CAMPOS_SOLO_DE_FACTURA}
    documento.update({
        'iTiDE': '5',
        'dNumTim': settings.FACTURACION_TIMBRADO,
        'dFeIniT': settings.FACTURACION_TIMBRADO_INICIO,
        'dEst': settings.FACTURACION_ESTABLECIMIENTO,
        'dPunExp': settings.FACTURACION_PUNTO_EXPEDICION,
        'dNumDoc': f'{numero:07d}',
        'dFeEmiDE': emitida_en.astimezone(HORA_DE_PARAGUAY).strftime('%Y-%m-%dT%H:%M:%S'),
        'iMotEmi': MOTIVO_DE_LA_NOTA,
        'gCamDEAsoc': [{
            'iTipDocAso': '1',  # documento electrónico asociado
            'dCdCDERef': factura.cdc,
            'dNTimDI': '0', 'dEstDocAso': '0', 'dPExpDocAso': '0', 'dNumDocAso': '0',
            'iTipoDocAso': '1',
            'dFecEmiDI': str(base.get('dFeEmiDE', ''))[:10] or str(emitida_en.date()),
            'dNumComRet': '0', 'dNumResCF': '0', 'iTipCons': '0', 'dNumCons': '0',
            'dNumControl': '0',
        }],
        'CDC': '0',
        'dCodSeg': '0',
        'dDVId': '0',
        'dInfAdic': (
            f'Anula la factura {factura.numero} de la operación #{factura.transaccion_id}.'
        ),
    })
    return documento


def anular_factura(factura, usuario=None):
    """Anula una factura y, si estaba emitida, emite su nota de crédito (E4-191).
    Devuelve la ``NotaCredito`` creada, o ``None`` si no hizo falta.

    * ``EMITIDA``: queda ``ANULADA`` y se crea una nota de crédito ``PENDIENTE`` por el
      total, vinculada a ella, que se envía al proveedor cuando se confirma la
      transacción de base de datos (con reintentos, como la factura).
    * ``PENDIENTE`` o ``RECHAZADA``: nunca existió para SIFEN, así que queda ``ANULADA``
      sin nota de crédito.
    * ``ANULADA`` (ya se anuló) o ``ENVIADA`` (SIFEN todavía no la aprobó): se rechaza
      con ``ValidationError`` y un mensaje claro, sin tocar nada.

    La anulación queda en la auditoría con el ``usuario`` (o el sistema). Debe llamarse
    dentro de la transacción que anula la operación: si algo falla, no se anula nada.
    """
    with transaction.atomic():
        factura = Factura.objects.select_for_update().get(pk=factura.pk)
        if factura.estado == Factura.ANULADA:
            raise ValidationError(f'La factura {factura.numero} ya fue anulada.')
        if factura.estado == Factura.ENVIADA:
            raise ValidationError(
                f'La factura {factura.numero} todavía espera la aprobación de SIFEN: '
                f'se puede anular cuando quede emitida.'
            )

        nota = None
        if factura.estado == Factura.EMITIDA:
            ahora = timezone.now()
            establecimiento = settings.FACTURACION_ESTABLECIMIENTO
            punto = settings.FACTURACION_PUNTO_EXPEDICION
            numero = SecuenciaFactura.siguiente(establecimiento, punto, SecuenciaFactura.NOTA_CREDITO)
            nota = NotaCredito.objects.create(
                factura=factura,
                establecimiento=establecimiento,
                punto_expedicion=punto,
                correlativo=numero,
                timbrado=settings.FACTURACION_TIMBRADO,
                monto=factura.monto,
                motivo='Anulación de la operación en efectivo',
                fecha_emision=ahora,
                payload=construir_nota_credito(factura, numero, ahora),
            )
            transaction.on_commit(lambda: enviar_nota(nota.pk))
            detalle = f'Nota de crédito {nota.numero} por {factura.monto:.2f} Gs'
        else:
            detalle = 'Sin nota de crédito: la factura nunca se emitió'

        factura.estado = Factura.ANULADA
        factura.save(update_fields=['estado'])
        EventoFactura.registrar(factura, EventoFactura.ANULACION, usuario, detalle)
    return nota


def anular_factura_de(transaccion, usuario=None):
    """Anula la factura de una operación (si tiene). Ver ``anular_factura``."""
    factura = Factura.objects.filter(transaccion=transaccion).first()
    if factura is None:
        return None
    return anular_factura(factura, usuario)


def _armar_correo(factura, destinatario):
    """El correo con la factura: un texto corto y el PDF adjunto."""
    from .services import generar_pdf  # el PDF que ve y descarga el cliente

    concepto = factura.payload['gCamItem'][0]['dDesProSer']
    lineas = [
        f"Hola {factura.payload['dNomRec']},",
        '',
        f'Te enviamos tu factura electrónica N° {factura.numero} por: {concepto}.',
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
        subject=f'Factura electrónica {factura.numero} - GlobalExchange',
        body='\n'.join(lineas),
        to=[destinatario],
    )
    mensaje.attach(f'factura-{factura.numero}.pdf', generar_pdf(factura), 'application/pdf')
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


def _consultar(modelo, documento_id):
    """Pregunta a SIFEN (por el proveedor) cómo quedó una factura o nota de crédito
    ``ENVIADA``. Si no se puede consultar, anota el motivo y la deja como está."""
    with transaction.atomic():
        documento = (
            modelo.objects.select_for_update(skip_locked=True)
            .filter(pk=documento_id, estado=Factura.ENVIADA).first()
        )
        if documento is None:
            return None
        try:
            proveedor = obtener_proveedor()
            respuesta = proveedor.consultar(documento.cdc)
        except ErrorFacturacion as exc:
            logger.warning('No se pudo consultar %s %s: %s', modelo.__name__, documento.pk, exc)
            documento.ultimo_error = str(exc)[:255]
        except Exception:
            logger.exception('Error inesperado al consultar %s %s', modelo.__name__, documento.pk)
            documento.ultimo_error = 'Error inesperado al consultar el documento.'
        else:
            _aplicar_respuesta(documento, respuesta, proveedor)
        documento.save()
    return documento


def consultar_estado(factura_id):
    """Pregunta a SIFEN cómo quedó una factura ``ENVIADA`` y, si quedó emitida, la manda
    por correo. Devuelve la factura o ``None`` si ya no estaba enviada."""
    factura = _consultar(Factura, factura_id)
    if factura is not None and factura.estado == Factura.EMITIDA:
        enviar_por_correo(factura.pk)
    return factura


def consultar_estado_nota(nota_id):
    """Lo mismo que ``consultar_estado`` para una nota de crédito (sin correo)."""
    return _consultar(NotaCredito, nota_id)


def procesar_pendientes(ahora=None):
    """Pone al día todas las facturas y notas de crédito. Devuelve cuántas hizo de cada
    cosa::

        {'registradas': ..., 'enviadas': ..., 'consultadas': ..., 'correos': ...}

    1. Crea la factura de las operaciones exitosas que no la tengan.
    2. Reintenta las ``PENDIENTE`` (facturas y notas de crédito) cuya hora de reintento
       ya llegó.
    3. Consulta a SIFEN las ``ENVIADA`` (facturas y notas de crédito).
    4. Manda por correo las facturas ``EMITIDA`` cuyo correo todavía no salió (``correos``
       cuenta solo estos reenvíos: los correos que salen en los pasos anteriores no se
       suman).
    """
    ahora = ahora or timezone.now()
    resumen = {'registradas': 0, 'enviadas': 0, 'consultadas': 0, 'correos': 0}

    for operacion in Transaccion.objects.filter(estado='EXITOSA', factura__isnull=True):
        with transaction.atomic():
            _, creada = registrar_factura(operacion)
        resumen['registradas'] += creada

    for modelo, enviar_documento, consultar_documento in (
        (Factura, enviar, consultar_estado),
        (NotaCredito, enviar_nota, consultar_estado_nota),
    ):
        pendientes = modelo.objects.filter(estado=Factura.PENDIENTE).exclude(
            proximo_intento__gt=ahora
        ).values_list('pk', flat=True)
        for pk in list(pendientes):
            documento = enviar_documento(pk, ahora)
            resumen['enviadas'] += documento is not None and documento.estado != Factura.PENDIENTE

        for pk in list(modelo.objects.filter(estado=Factura.ENVIADA).values_list('pk', flat=True)):
            resumen['consultadas'] += consultar_documento(pk) is not None

    if settings.FACTURACION_ENVIAR_CORREO:
        sin_correo = Factura.objects.filter(
            estado=Factura.EMITIDA, correo_enviado_en__isnull=True
        ).values_list('pk', flat=True)
        for pk in list(sin_correo):
            resumen['correos'] += enviar_por_correo(pk)

    return resumen
