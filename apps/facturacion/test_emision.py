"""Tests de la emisión de facturas electrónicas: emisión automática, reintentos, correo, y
los dos proveedores (el simulador y Factura Segura, con la red simulada). Las pantallas de
consulta y descarga se prueban en ``tests``. Nada habla con Factura Segura de verdad."""
import smtplib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone

from apps.divisas.models import Moneda, TasaCambio
from apps.facturacion import emision, proveedores
from apps.facturacion.models import Factura, SecuenciaFactura
from apps.facturacion.proveedores import ErrorFacturacion
from apps.transacciones.models import MedioPagoCliente, MetodoPago, Transaccion
from apps.transacciones.tests import _cliente, _usuario_con_rol
from apps.usuarios.models import Cliente, Usuario

OPERAR = '/api/transacciones/gestion/operar/'

class BaseFacturacionTests(TestCase):
    """Dos clientes VIP (sin límite) que operan en efectivo, con su usuario cada uno, y
    un analista y un administrador."""

    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.tasa = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')

        self.cliente = _cliente(nombre='Cliente Uno', documento='4725453', categoria=Cliente.CATEGORIA_VIP)
        self.user = _usuario_con_rol('final_fact', rol='usuario_final')
        Usuario.objects.create(
            username='final_fact', email='final@example.com', nombres='F', apellidos='F',
        ).clientes.add(self.cliente)
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, alias='Efectivo', identificador='EFECTIVO', metodo_pago=metodo,
        )
        self.client.force_login(self.user)

        self.otro_cliente = _cliente(nombre='Cliente Dos', documento='1234567', categoria=Cliente.CATEGORIA_VIP)
        self.otro_user = _usuario_con_rol('otro_fact', rol='usuario_final')
        Usuario.objects.create(
            username='otro_fact', email='otro@example.com', nombres='O', apellidos='O',
        ).clientes.add(self.otro_cliente)
        self.otro_medio = MedioPagoCliente.objects.create(
            cliente=self.otro_cliente, alias='Efectivo', identificador='EFECTIVO', metodo_pago=metodo,
        )
        self.client_otro = Client()
        self.client_otro.force_login(self.otro_user)

        self.analista = _usuario_con_rol('analista_fact', rol='analista')
        self.admin = _usuario_con_rol('admin_fact', rol='administrador')

    def _operar(self, tipo='COMPRA', cantidad='10', medio=None, http=None, confirmar=True, enviar=True):
        """El cliente opera y confirma. Con ``enviar`` también corre el envío de la
        factura, que se hace al confirmarse la transacción de base de datos (en los tests
        no hay commit real, así que se ejecuta a mano)."""
        medio = medio or self.medio
        http = http or self.client
        http.post(OPERAR, {
            'tipo': tipo, 'moneda_codigo': 'USD', 'cantidad': cantidad, 'medio_pago_id': medio.id,
        })
        operacion = Transaccion.objects.filter(cliente=medio.cliente).latest('pk')
        if confirmar:
            with self.captureOnCommitCallbacks(execute=enviar):
                http.post(f'{OPERAR}{operacion.pk}/confirmar/')
            operacion.refresh_from_db()
        return operacion


class EmisionDeLaFacturaTests(BaseFacturacionTests):
    def test_al_pagarse_la_operacion_se_emite_la_factura_con_todos_los_datos(self):
        operacion = self._operar()
        self.assertEqual(operacion.estado, 'EXITOSA')
        factura = Factura.objects.get(transaccion=operacion)
        self.assertEqual(factura.estado, Factura.EMITIDA)
        self.assertEqual(factura.numero, '001-001-0000001')
        self.assertEqual(factura.monto, Decimal('75110.00'))  # 10 x 7.400 + 1,5%
        self.assertEqual(factura.proveedor, 'SIMULADO')
        self.assertRegex(factura.cdc, r'^\d{44}$')
        self.assertIsNotNone(factura.fecha_emision)
        self.assertEqual(factura.ultimo_error, '')
        datos = factura.payload
        self.assertEqual(datos['dNumDoc'], '0000001')
        self.assertEqual(datos['dNomRec'], 'Cliente Uno')
        self.assertEqual(datos['dEmailRec'], 'final@example.com')
        self.assertEqual(datos['cMoneOpe'], 'PYG')
        item = datos['gCamItem'][0]
        self.assertEqual(item['dPUniProSer'], '75110')
        self.assertEqual(item['dDesProSer'], f'Compra de 10.00 USD (operación #{operacion.pk})')
        self.assertIn('1 USD = 7400.00 Gs', datos['dInfAdic'])  # tasa aplicada
        self.assertIn('Comisión 1.50% (1110 Gs)', datos['dInfAdic'])  # comisión

    def test_la_factura_nace_pendiente_y_se_envia_al_confirmarse_la_transaccion(self):
        self.client.post(OPERAR, {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        operacion = Transaccion.objects.get()
        with self.captureOnCommitCallbacks(execute=False) as envios:
            self.client.post(f'{OPERAR}{operacion.pk}/confirmar/')
        factura = Factura.objects.get()
        self.assertEqual(len(envios), 1)  # el envío espera al commit
        self.assertEqual(factura.estado, Factura.PENDIENTE)
        envios[0]()
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.EMITIDA)

    def test_una_operacion_no_puede_tener_dos_facturas(self):
        operacion = self._operar()
        original = Factura.objects.get()
        otra, creada = emision.registrar_factura(operacion)
        self.assertFalse(creada)
        self.assertEqual(otra.pk, original.pk)
        self.assertEqual(Factura.objects.count(), 1)
        self.assertEqual(SecuenciaFactura.objects.get().ultimo_numero, 1)  # no gastó otro número
        with self.assertRaises(IntegrityError), transaction.atomic():
            Factura.objects.create(transaccion=operacion, monto=Decimal('1'))

    def test_la_numeracion_es_correlativa(self):
        primera = self._operar()
        segunda = self._operar(cantidad='5')
        tercera = self._operar(http=self.client_otro, medio=self.otro_medio)
        numeros = [Factura.objects.get(transaccion=t).numero for t in (primera, segunda, tercera)]
        self.assertEqual(numeros, ['001-001-0000001', '001-001-0000002', '001-001-0000003'])

    def test_tambien_se_factura_una_venta(self):
        venta = self._operar('VENTA')
        factura = Factura.objects.get(transaccion=venta)
        # 10 x 7.300 - 1,5% = 71.905
        self.assertEqual(factura.monto, Decimal('71905.00'))
        self.assertEqual(factura.payload['gCamItem'][0]['dDesProSer'][:8], 'Venta de')

    def test_una_operacion_cancelada_no_genera_factura(self):
        operacion = self._operar(confirmar=False)
        self.client.post(f'{OPERAR}{operacion.pk}/cancelar/')
        self.assertEqual(Factura.objects.count(), 0)

    def test_si_cambia_la_cotizacion_la_operacion_se_cancela_y_no_hay_factura(self):
        operacion = self._operar(confirmar=False)
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        self.client.post(f'{OPERAR}{operacion.pk}/confirmar/')
        operacion.refresh_from_db()
        self.assertEqual(operacion.estado, 'CANCELADA')
        self.assertEqual(Factura.objects.count(), 0)

    def test_si_no_se_pudo_crear_la_factura_la_operacion_sigue_exitosa_y_el_comando_la_crea(self):
        self.client.post(OPERAR, {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        operacion = Transaccion.objects.get()
        with mock.patch('apps.facturacion.emision.registrar_factura', side_effect=RuntimeError('boom')), \
                self.assertLogs('apps.transacciones.models', level='ERROR'):
            self.client.post(f'{OPERAR}{operacion.pk}/confirmar/')
        operacion.refresh_from_db()
        self.assertEqual(operacion.estado, 'EXITOSA')
        self.assertEqual(Factura.objects.count(), 0)

        resumen = emision.procesar_pendientes()
        self.assertEqual(
            resumen, {'registradas': 1, 'enviadas': 1, 'consultadas': 0, 'correos': 0}
        )
        self.assertEqual(Factura.objects.get(transaccion=operacion).estado, Factura.EMITIDA)


class ProveedorCaidoYReintentosTests(BaseFacturacionTests):
    def _con_proveedor_caido(self):
        return override_settings(FACTURACION_SIMULADOR_DISPONIBLE=False)

    def test_si_el_proveedor_esta_caido_la_operacion_sigue_exitosa_y_la_factura_queda_pendiente(self):
        with self._con_proveedor_caido(), self.assertLogs('apps.facturacion.emision', level='WARNING'):
            operacion = self._operar()
        self.assertEqual(operacion.estado, 'EXITOSA')  # no se revierte
        factura = Factura.objects.get(transaccion=operacion)
        self.assertEqual(factura.estado, Factura.PENDIENTE)
        self.assertEqual(factura.intentos, 1)
        self.assertIn('no está disponible', factura.ultimo_error)
        # reintento programado en un minuto
        espera = factura.proximo_intento - dj_timezone.now()
        self.assertTrue(timedelta(seconds=30) < espera <= timedelta(minutes=1))

    def test_si_el_proveedor_falla_con_un_error_inesperado_tampoco_se_rompe_nada(self):
        with mock.patch('apps.facturacion.emision.obtener_proveedor', side_effect=RuntimeError('x')), \
                self.assertLogs('apps.facturacion.emision', level='ERROR'):
            operacion = self._operar()
        self.assertEqual(operacion.estado, 'EXITOSA')
        factura = Factura.objects.get()
        self.assertEqual(factura.estado, Factura.PENDIENTE)
        self.assertEqual(factura.ultimo_error, 'Error inesperado al enviar la factura.')

    def test_se_reintenta_cuando_llega_la_hora_y_se_emite_al_volver_el_proveedor(self):
        with self._con_proveedor_caido(), self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self._operar()
        factura = Factura.objects.get()
        antes = factura.proximo_intento - timedelta(seconds=10)

        # todavía no es la hora: no se toca
        self.assertEqual(emision.procesar_pendientes(ahora=antes)['enviadas'], 0)
        factura.refresh_from_db()
        self.assertEqual(factura.intentos, 1)

        # llega la hora pero el proveedor sigue caído: nuevo intento, con más espera
        hora = factura.proximo_intento + timedelta(seconds=1)
        with self._con_proveedor_caido(), self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self.assertEqual(emision.procesar_pendientes(ahora=hora)['enviadas'], 0)
        factura.refresh_from_db()
        self.assertEqual(factura.intentos, 2)
        self.assertEqual(factura.proximo_intento, hora + timedelta(minutes=2))

        # el proveedor vuelve: queda emitida y se borra el error
        hora = factura.proximo_intento + timedelta(seconds=1)
        self.assertEqual(emision.procesar_pendientes(ahora=hora)['enviadas'], 1)
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.EMITIDA)
        self.assertEqual((factura.ultimo_error, factura.proximo_intento), ('', None))
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')

    def test_la_espera_entre_reintentos_crece_y_tiene_techo(self):
        ahora = datetime(2026, 10, 12, tzinfo=timezone.utc)
        minutos = [(emision._siguiente_intento(n, ahora) - ahora).seconds // 60 for n in (1, 2, 3, 4, 9, 30)]
        self.assertEqual(minutos, [1, 2, 4, 8, 60, 60])

    def test_enviar_una_factura_que_ya_no_esta_pendiente_no_hace_nada(self):
        self._operar()
        factura = Factura.objects.get()
        with mock.patch('apps.facturacion.emision.obtener_proveedor') as proveedor:
            self.assertIsNone(emision.enviar(factura.pk))
        proveedor.assert_not_called()

    def test_el_comando_informa_lo_que_hizo(self):
        with self._con_proveedor_caido(), self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self._operar()
        salida = StringIO()
        call_command('procesar_facturas', stdout=salida)
        texto = salida.getvalue()
        self.assertIn('Facturas creadas: 0 | enviadas: 0', texto)  # todavía no es la hora
        self.assertIn('Pendiente de envío: 1', texto)


class CorreoDeLaFacturaTests(BaseFacturacionTests):
    """Al emitirse, la factura llega al correo del usuario que hizo la operación."""

    def test_al_emitirse_llega_al_correo_del_cliente_con_el_pdf_adjunto(self):
        self._operar()
        factura = Factura.objects.get()
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['final@example.com'])
        self.assertEqual(correo.subject, 'Factura electrónica 001-001-0000001 - GlobalExchange')
        for texto in ('Hola Cliente Uno', '001-001-0000001', 'Compra de 10.00 USD', '75.110,00 Gs'):
            self.assertIn(texto, correo.body)
        self.assertIn('documento de prueba', correo.body)  # el simulador no tiene validez
        self.assertEqual(len(correo.attachments), 1)
        nombre, contenido, tipo = correo.attachments[0]
        self.assertEqual((nombre, tipo), ('factura-001-001-0000001.pdf', 'application/pdf'))
        self.assertTrue(contenido.startswith(b'%PDF'))
        self.assertIsNotNone(factura.correo_enviado_en)
        self.assertEqual(factura.correo_error, '')

    def test_cada_factura_va_al_usuario_que_hizo_su_operacion(self):
        self._operar()
        self._operar(http=self.client_otro, medio=self.otro_medio)
        self.assertEqual([c.to for c in mail.outbox], [['final@example.com'], ['otro@example.com']])

    def test_no_sale_correo_mientras_la_factura_no_esta_emitida(self):
        with override_settings(FACTURACION_SIMULADOR_DISPONIBLE=False), \
                self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self._operar()
        self.assertEqual(Factura.objects.get().estado, Factura.PENDIENTE)
        self.assertEqual(mail.outbox, [])
        # cuando el proveedor vuelve y se emite, recién ahí sale el correo
        emision.procesar_pendientes(ahora=dj_timezone.now() + timedelta(hours=2))
        self.assertEqual(len(mail.outbox), 1)

    def test_el_correo_sale_una_sola_vez(self):
        self._operar()
        factura = Factura.objects.get()
        self.assertFalse(emision.enviar_por_correo(factura.pk))
        self.assertEqual(emision.procesar_pendientes()['correos'], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_si_el_correo_falla_la_factura_sigue_emitida_y_se_reintenta(self):
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=smtplib.SMTPException('SMTP caído')), \
                self.assertLogs('apps.facturacion.emision', level='WARNING'):
            operacion = self._operar()
        factura = Factura.objects.get()
        self.assertEqual(operacion.estado, 'EXITOSA')
        self.assertEqual(factura.estado, Factura.EMITIDA)  # la factura no se toca
        self.assertIsNone(factura.correo_enviado_en)
        self.assertIn('SMTP caído', factura.correo_error)
        self.assertEqual(mail.outbox, [])

        self.assertEqual(emision.procesar_pendientes()['correos'], 1)
        factura.refresh_from_db()
        self.assertIsNotNone(factura.correo_enviado_en)
        self.assertEqual(factura.correo_error, '')
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(FACTURACION_ENVIAR_CORREO=False)
    def test_se_puede_apagar_el_envio_por_correo(self):
        self._operar()
        factura = Factura.objects.get()
        self.assertEqual(factura.estado, Factura.EMITIDA)
        self.assertEqual(mail.outbox, [])
        self.assertIsNone(factura.correo_enviado_en)
        self.assertEqual(emision.procesar_pendientes()['correos'], 0)

    def test_sin_correo_del_receptor_no_se_manda_nada_ni_falla(self):
        self._operar(enviar=False)
        factura = Factura.objects.get()
        Factura.objects.filter(pk=factura.pk).update(
            payload={**factura.payload, 'dEmailRec': ''}
        )
        emision.enviar(factura.pk)
        self.assertEqual(Factura.objects.get().estado, Factura.EMITIDA)
        self.assertEqual(mail.outbox, [])

    def test_el_comando_informa_los_correos_reenviados(self):
        salida = StringIO()
        call_command('procesar_facturas', stdout=salida)
        self.assertIn('correos reenviados: 0', salida.getvalue())


class ContenidoDelDocumentoTests(BaseFacturacionTests):
    def _documento(self, operacion, numero=7, emitida_en=None):
        emitida_en = emitida_en or datetime(2026, 10, 12, 15, 30, 5, tzinfo=timezone.utc)
        return emision.construir_documento(operacion, numero, emitida_en)

    def test_la_hora_es_la_de_paraguay_y_el_numero_lleva_siete_digitos(self):
        documento = self._documento(self._operar(confirmar=False))
        self.assertEqual(documento['dFeEmiDE'], '2026-10-12T12:30:05')
        self.assertEqual(documento['dNumDoc'], '0000007')

    def test_un_cliente_con_cedula_es_receptor_no_contribuyente(self):
        documento = self._documento(self._operar(confirmar=False))
        self.assertEqual(
            (documento['iNatRec'], documento['iTiOpe'], documento['iTiContRec']), ('2', '2', '1')
        )
        self.assertEqual((documento['iTipIDRec'], documento['dNumIDRec']), ('1', '4725453'))
        self.assertNotIn('dRucRec', documento)

    def test_un_cliente_con_ruc_es_receptor_contribuyente(self):
        Cliente.objects.filter(pk=self.cliente.pk).update(documento='80012345-6', tipo='JURIDICA')
        documento = self._documento(self._operar(confirmar=False))
        self.assertEqual(
            (documento['iNatRec'], documento['iTiOpe'], documento['iTiContRec']), ('1', '1', '2')
        )
        self.assertEqual((documento['dRucRec'], documento['dDVRec']), ('80012345', '6'))

    def test_el_pago_lleva_el_tipo_de_pago_de_sifen_segun_el_metodo(self):
        operacion = self._operar(confirmar=False)
        esperados = {
            MetodoPago.TIPO_EFECTIVO: '1', MetodoPago.TIPO_TARJETA_CREDITO: '3',
            MetodoPago.TIPO_TRANSFERENCIA: '5', MetodoPago.TIPO_BILLETERA: '7',
        }
        for tipo, codigo in esperados.items():
            with self.subTest(tipo=tipo):
                operacion.metodo_pago.tipo = tipo  # sin guardar: solo se arma el documento
                pago = self._documento(operacion)['gPaConEIni'][0]
                self.assertEqual(pago['iTiPago'], codigo)
                self.assertEqual(pago['dMonTiPag'], '75110')

    def test_la_tarjeta_informa_la_forma_de_procesamiento(self):
        operacion = self._operar(confirmar=False)
        operacion.metodo_pago.tipo = MetodoPago.TIPO_TARJETA_CREDITO
        pago = self._documento(operacion)['gPaConEIni'][0]
        self.assertEqual((pago['iDenTarj'], pago['iForProPa']), ('99', '2'))

    def test_presencial_o_digital_se_informa_en_el_indicador_de_presencia(self):
        operacion = self._operar(confirmar=False)
        self.assertEqual(self._documento(operacion)['iIndPres'], '2')
        operacion.modalidad = 'PRESENCIAL'
        self.assertEqual(self._documento(operacion)['iIndPres'], '1')

    @override_settings(FACTURACION_EMISOR={
        **settings.FACTURACION_EMISOR, 'ruc': '80099999', 'dv': '4', 'nombre': 'OTRA CASA DE CAMBIO',
    })
    def test_el_emisor_sale_de_la_configuracion(self):
        documento = self._documento(self._operar(confirmar=False))
        self.assertEqual(
            (documento['dRucEm'], documento['dDVEmi'], documento['dNomEmi']),
            ('80099999', '4', 'OTRA CASA DE CAMBIO'),
        )


class ProveedorSimuladoTests(SimpleTestCase):
    PAYLOAD = {
        'iTiDE': '1', 'dRucEm': '80000000', 'dDVEmi': '0', 'dEst': '001', 'dPunExp': '001',
        'dNumDoc': '0000001', 'iTipCont': '2', 'dFeEmiDE': '2026-10-12T12:30:05', 'iTipEmi': '1',
    }

    def test_aprueba_y_fabrica_un_cdc_de_44_digitos_con_su_digito_verificador(self):
        respuesta = proveedores.ProveedorSimulado().emitir(self.PAYLOAD)
        self.assertEqual(respuesta.estado_sifen, 'Aprobado')
        self.assertRegex(respuesta.cdc, r'^\d{44}$')
        self.assertTrue(respuesta.cdc.startswith('01' + '80000000' + '0' + '001' + '001' + '0000001'))
        self.assertEqual(proveedores._digito_verificador(respuesta.cdc[:43]), respuesta.cdc[43])

    def test_el_cdc_es_estable_y_distinto_por_documento(self):
        simulado = proveedores.ProveedorSimulado()
        primero = simulado.emitir(self.PAYLOAD).cdc
        self.assertEqual(primero, simulado.emitir(self.PAYLOAD).cdc)
        otro = simulado.emitir({**self.PAYLOAD, 'dNumDoc': '0000002'}).cdc
        self.assertNotEqual(primero, otro)

    @override_settings(FACTURACION_SIMULADOR_DISPONIBLE=False)
    def test_caido_no_emite_ni_consulta(self):
        simulado = proveedores.ProveedorSimulado()
        with self.assertRaisesMessage(ErrorFacturacion, 'no está disponible'):
            simulado.emitir(self.PAYLOAD)
        with self.assertRaisesMessage(ErrorFacturacion, 'no está disponible'):
            simulado.consultar('1' * 44)

    def test_la_factura_de_las_pruebas_usa_el_simulador(self):
        self.assertIsInstance(proveedores.obtener_proveedor(), proveedores.ProveedorSimulado)

    @override_settings(FACTURACION_PROVEEDOR='facturasegura')
    def test_obtener_proveedor_elige_factura_segura(self):
        self.assertIsInstance(proveedores.obtener_proveedor(), proveedores.ProveedorFacturaSegura)

    @override_settings(FACTURACION_PROVEEDOR='otro')
    def test_un_proveedor_desconocido_es_un_error(self):
        with self.assertRaisesMessage(ErrorFacturacion, 'desconocido'):
            proveedores.obtener_proveedor()


def _respuesta_http(datos=None, status=200, json_invalido=False):
    respuesta = mock.Mock(status_code=status)
    if json_invalido:
        respuesta.json.side_effect = ValueError('no es JSON')
    else:
        respuesta.json.return_value = datos
    return respuesta


@override_settings(
    FACTURACION_PROVEEDOR='facturasegura', FACTURA_SEGURA_TOKEN='token-de-prueba',
    FACTURA_SEGURA_URL='https://api.prueba/misife00/v1/esi',
)
class ProveedorFacturaSeguraTests(SimpleTestCase):
    """El cliente de Factura Segura contra respuestas armadas según el contrato del
    documento de la API."""

    PAYLOAD = {'iTiDE': '1', 'dNumDoc': '0000001'}
    CDC = '01800000000000010010000001212026101212345678'

    def _emitir_con(self, *respuestas):
        with mock.patch('requests.post', side_effect=list(respuestas)) as post:
            resultado = proveedores.ProveedorFacturaSegura().emitir(self.PAYLOAD)
        return resultado, post

    def test_emitir_calcula_y_genera_el_documento(self):
        resultado, post = self._emitir_con(
            _respuesta_http({'code': 0, 'description': 'OK', 'results': [{'DE': {'calculado': True}}]}),
            _respuesta_http({'code': 0, 'description': 'OK', 'results': [{'CDC': self.CDC}]}),
        )
        self.assertEqual((resultado.cdc, resultado.estado_sifen), (self.CDC, 'SOL.APROBACION'))
        primera, segunda = post.call_args_list
        self.assertEqual(primera.args, ('https://api.prueba/misife00/v1/esi',))
        self.assertEqual(
            primera.kwargs['json'], {'operation': 'calcular_de', 'params': {'DE': self.PAYLOAD}}
        )
        # generar_de recibe el documento ya calculado por Factura Segura
        self.assertEqual(
            segunda.kwargs['json'], {'operation': 'generar_de', 'params': {'DE': {'calculado': True}}}
        )
        for llamada in post.call_args_list:
            self.assertEqual(llamada.kwargs['headers']['Authentication-Token'], 'token-de-prueba')
            self.assertEqual(llamada.kwargs['timeout'], proveedores.TIEMPO_DE_ESPERA)

    def test_un_code_negativo_es_un_error_con_la_descripcion_del_proveedor(self):
        with self.assertRaisesMessage(ErrorFacturacion, 'El valor del campo iTiOpe no es permitido'):
            self._emitir_con(_respuesta_http({
                'code': -10001, 'description': 'El valor del campo iTiOpe no es permitido', 'results': [],
            }))

    def test_los_errores_de_comunicacion_se_traducen(self):
        casos = (
            (requests.ConnectionError('sin red'), 'No se pudo conectar con Factura Segura'),
            (requests.Timeout('lento'), 'No se pudo conectar con Factura Segura'),
            (_respuesta_http(status=500), 'HTTP 500'),
            (_respuesta_http(json_invalido=True), 'respuesta inválida'),
            (_respuesta_http({'sin': 'code'}), 'respuesta inválida'),
            (_respuesta_http({'code': 0, 'results': []}), 'respuesta inesperada'),
        )
        for respuesta, mensaje in casos:
            with self.subTest(mensaje=mensaje), self.assertRaisesMessage(ErrorFacturacion, mensaje):
                self._emitir_con(respuesta)

    @override_settings(FACTURA_SEGURA_TOKEN='')
    def test_sin_token_ni_siquiera_llama_a_la_red(self):
        with mock.patch('requests.post') as post:
            with self.assertRaisesMessage(ErrorFacturacion, 'FACTURA_SEGURA_TOKEN'):
                proveedores.ProveedorFacturaSegura().emitir(self.PAYLOAD)
        post.assert_not_called()

    def test_consultar_pregunta_el_estado_con_el_ruc_del_emisor(self):
        estado = {'estado_sifen': 'Aprobado', 'desc_sifen': '0260 - Aprobado', 'error_sifen': ''}
        with mock.patch('requests.post', return_value=_respuesta_http(
            {'code': 0, 'description': 'OK', 'results': [estado]}
        )) as post:
            respuesta = proveedores.ProveedorFacturaSegura().consultar(self.CDC)
        self.assertEqual(respuesta.estado_sifen, 'Aprobado')
        self.assertEqual(respuesta.descripcion, '0260 - Aprobado')
        self.assertEqual(post.call_args.kwargs['json'], {
            'operation': 'get_estado_sifen',
            'params': {'CDC': self.CDC, 'dRucEm': '80000000'},
        })

    def test_consultar_sin_resultados_es_un_error(self):
        with mock.patch('requests.post', return_value=_respuesta_http({'code': 0, 'results': []})):
            with self.assertRaisesMessage(ErrorFacturacion, 'no devolvió el estado'):
                proveedores.ProveedorFacturaSegura().consultar(self.CDC)


class FacturaSeguraConLaAplicacionTests(BaseFacturacionTests):
    """El recorrido completo con Factura Segura: enviada, y emitida cuando SIFEN aprueba."""

    CDC = '01800000000000010010000001212026101212345678'

    def _respuestas_de_emision(self):
        return [
            _respuesta_http({'code': 0, 'results': [{'DE': {'ok': True}}]}),
            _respuesta_http({'code': 0, 'results': [{'CDC': self.CDC}]}),
        ]

    def _estado(self, estado_sifen, descripcion='', error=''):
        return _respuesta_http({'code': 0, 'results': [{
            'estado_sifen': estado_sifen, 'desc_sifen': descripcion, 'error_sifen': error,
        }]})

    def _operar_con_factura_segura(self):
        with self.settings(
            FACTURACION_PROVEEDOR='facturasegura', FACTURA_SEGURA_TOKEN='tok'
        ), mock.patch('requests.post', side_effect=self._respuestas_de_emision()):
            self._operar()
        return Factura.objects.get()

    def _consultar(self, *respuestas):
        with self.settings(
            FACTURACION_PROVEEDOR='facturasegura', FACTURA_SEGURA_TOKEN='tok'
        ), mock.patch('requests.post', side_effect=list(respuestas)):
            return emision.procesar_pendientes()

    def test_queda_enviada_con_su_cdc_hasta_que_sifen_resuelve(self):
        factura = self._operar_con_factura_segura()
        self.assertEqual(
            (factura.estado, factura.cdc, factura.proveedor), (Factura.ENVIADA, self.CDC, 'FACTURA_SEGURA')
        )
        self.assertFalse(factura.esta_emitida)

        resumen = self._consultar(self._estado('SOL.APROBACION'))
        factura.refresh_from_db()
        self.assertEqual(resumen['consultadas'], 1)
        self.assertEqual(factura.estado, Factura.ENVIADA)  # SIFEN todavía no resolvió

    def test_sifen_aprueba(self):
        factura = self._operar_con_factura_segura()
        self._consultar(self._estado('Aprobado', '0260 - Aprobado'))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.EMITIDA)
        self.assertEqual(factura.estado_sifen, '0260 - Aprobado')

    def test_sifen_aprueba_con_observacion(self):
        factura = self._operar_con_factura_segura()
        self._consultar(self._estado('Aprobado con observación', '0261 - Aprobado con observación'))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.EMITIDA)

    def test_sifen_rechaza(self):
        factura = self._operar_con_factura_segura()
        self._consultar(self._estado('Rechazado', '1000 - RUC inválido'))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.RECHAZADA)
        self.assertEqual(factura.ultimo_error, '1000 - RUC inválido')
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')  # la operación no se toca

    def test_si_no_se_puede_consultar_sigue_enviada_con_el_motivo(self):
        factura = self._operar_con_factura_segura()
        with self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self._consultar(requests.ConnectionError('sin red'))
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.ENVIADA)
        self.assertIn('No se pudo conectar', factura.ultimo_error)

    def test_si_factura_segura_rechaza_el_envio_queda_pendiente_para_reintentar(self):
        with self.settings(FACTURACION_PROVEEDOR='facturasegura', FACTURA_SEGURA_TOKEN='tok'), \
                mock.patch('requests.post', return_value=_respuesta_http({
                    'code': -10001, 'description': 'Longitud de campo incorrecta', 'results': [],
                })), self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self._operar()
        factura = Factura.objects.get()
        self.assertEqual(factura.estado, Factura.PENDIENTE)
        self.assertIn('Longitud de campo incorrecta', factura.ultimo_error)
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')

    def test_con_factura_segura_el_correo_sale_recien_cuando_sifen_aprueba(self):
        factura = self._operar_con_factura_segura()
        self.assertEqual(mail.outbox, [])  # enviada a SIFEN, todavía sin aprobar
        self._consultar(self._estado('SOL.APROBACION'))
        self.assertEqual(mail.outbox, [])
        self._consultar(self._estado('Aprobado', '0260 - Aprobado'))
        factura.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ['final@example.com'])
        self.assertNotIn('documento de prueba', correo.body)  # es un documento real
        self.assertIsNotNone(factura.correo_enviado_en)

    def test_si_sifen_rechaza_no_sale_correo(self):
        self._operar_con_factura_segura()
        self._consultar(self._estado('Rechazado', '1000 - RUC inválido'))
        self.assertEqual(mail.outbox, [])

    def test_estado_desde_sifen(self):
        casos = {
            'Aprobado': Factura.EMITIDA, 'aprobado con observacion': Factura.EMITIDA,
            'Rechazado': Factura.RECHAZADA, 'SOL.APROBACION': Factura.ENVIADA,
            'ENVIADO_A_SIFEN': Factura.ENVIADA, 'ERROR_SIFEN': Factura.ENVIADA, '': Factura.ENVIADA,
            None: Factura.ENVIADA,
        }
        for estado, esperado in casos.items():
            with self.subTest(estado=estado):
                self.assertEqual(emision.estado_desde_sifen(estado), esperado)


class FacturaEnLaOperacionTests(BaseFacturacionTests):
    """El resumen de la operación exitosa lleva a la factura (pantallas de ``tests``)."""

    def test_el_resumen_enlaza_a_la_factura_emitida_y_a_su_pdf(self):
        operacion = self._operar()
        factura = Factura.objects.get()
        resumen = self.client.get(f'{OPERAR}{operacion.pk}/')
        self.assertContains(resumen, 'Factura electrónica')
        self.assertContains(resumen, factura.numero)
        self.assertContains(resumen, reverse('detalle_factura', args=[factura.pk]))
        self.assertContains(resumen, reverse('descargar_factura_pdf', args=[factura.pk]))

    def test_si_la_factura_se_esta_emitiendo_el_resumen_lo_dice(self):
        operacion = self._operar()
        Factura.objects.filter(pk=Factura.objects.get().pk).update(estado=Factura.PENDIENTE)
        resumen = self.client.get(f'{OPERAR}{operacion.pk}/')
        self.assertContains(resumen, 'se está emitiendo')
        self.assertNotContains(resumen, 'descargar PDF')

    def test_la_factura_emitida_se_ve_y_se_descarga_desde_la_consulta(self):
        self._operar()
        factura = Factura.objects.get()
        self.assertContains(self.client.get(reverse('lista_facturas')), factura.numero)
        detalle = self.client.get(reverse('detalle_factura', args=[factura.pk]))
        self.assertContains(detalle, factura.numero)
        pdf = self.client.get(reverse('descargar_factura_pdf', args=[factura.pk]))
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_el_pdf_trae_los_datos_del_documento_que_se_envio(self):
        self._operar()
        factura = Factura.objects.get()
        from apps.facturacion.services import generar_pdf
        from reportlab import rl_config
        anterior = rl_config.pageCompression, rl_config.useA85
        rl_config.pageCompression, rl_config.useA85 = 0, 0
        try:
            pdf = generar_pdf(factura)
        finally:
            rl_config.pageCompression, rl_config.useA85 = anterior
        for dato in (factura.numero, factura.cdc, '80000000-0', '12345678', 'PRUEBA'):
            self.assertIn(dato.encode('latin-1'), pdf, dato)

    def test_el_filtro_por_numero_encuentra_el_correlativo(self):
        self._operar()
        self._operar(cantidad='5')
        segunda = Factura.objects.get(correlativo=2)
        resp = self.client.get(reverse('lista_facturas'), {'numero': segunda.numero})
        self.assertContains(resp, segunda.numero)
        self.assertNotContains(resp, '001-001-0000001')
