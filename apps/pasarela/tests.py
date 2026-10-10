"""Tests de la pasarela de pago simulada (E4-157/E4-158): el recorrido del cliente
va todo por pantallas, sin comandos."""
import json
from decimal import Decimal
from unittest import mock

from django.template.defaultfilters import floatformat
from django.test import TestCase

from apps.banco.models import CuentaBancaria
from apps.divisas.models import Moneda, TasaCambio
from apps.transacciones import webhook
from apps.transacciones.models import MedioPagoCliente, MetodoPago, Transaccion
from apps.transacciones.tests import _abrir_cuenta, _cliente, _usuario_con_rol
from apps.usuarios.models import Cliente, Usuario


class BasePasarelaTests(TestCase):
    """Un cliente VIP con una cuenta en el banco, que compra 10 USD."""

    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.tasa = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(nombre='Cliente Pasarela', documento='PSR-1', categoria=Cliente.CATEGORIA_VIP)
        self.user_final = _usuario_con_rol('final_pasarela', rol='usuario_final')
        Usuario.objects.create(
            username='final_pasarela', email='fp@example.com', nombres='F', apellidos='P',
        ).clientes.add(self.cliente)
        _abrir_cuenta('CA-PSR', CuentaBancaria.TIPO_CUENTA, 'PSR-1', saldo=Decimal('1000000'))
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, alias='Cuenta',
            metodo_pago=MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA'),
            identificador='CA-PSR',
        )
        self.client.force_login(self.user_final)

    def _operar_y_pedir_pasarela(self):
        """El cliente compra 10 USD y aprieta "Pagar con la pasarela"."""
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        self.tx = Transaccion.objects.get()
        return self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/pago-externo/', follow=True)

    @property
    def url_pasarela(self):
        self.tx.refresh_from_db()
        return f'/api/pasarela/pagar/{self.tx.referencia_pago_externo}/'

    def _saldo(self):
        return CuentaBancaria.objects.get(numero='CA-PSR').saldo


class RecorridoDelClienteTests(BasePasarelaTests):
    def test_comprar_pagar_en_la_pasarela_y_volver_con_la_operacion_confirmada(self):
        # 1) del botón a la pantalla de la pasarela
        resp = self._operar_y_pedir_pasarela()
        self.assertEqual(resp.redirect_chain[-1][0], self.url_pasarela)
        self.assertContains(resp, 'Pasarela de pago')
        self.assertContains(resp, 'SIMULACIÓN')
        self.assertContains(resp, self.tx.referencia_pago_externo)
        # 10 x 7.400 = 74.000 + 1,5% = 75.110
        self.assertContains(resp, f'{floatformat(Decimal("75110"), "2g")} Gs')
        self.assertContains(resp, 'Compra de 10,00 USD')
        for boton in ('Pagar', 'Rechazar', 'Volver sin pagar'):
            self.assertContains(resp, boton)
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')  # todavía no pagó

        # 2) paga en la pasarela y vuelve al resumen, ya confirmada
        resp = self.client.post(self.url_pasarela, {'accion': 'pagar'}, follow=True)
        self.assertRedirects(resp, f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resp, 'Pago confirmado')
        self.assertContains(resp, 'Exitosa')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'EXITOSA')
        # lo cobró la pasarela: no se debita además la cuenta del banco
        self.assertEqual(self._saldo(), Decimal('1000000.00'))

    def test_rechazar_en_la_pasarela_deja_la_operacion_fallida(self):
        self._operar_y_pedir_pasarela()
        resp = self.client.post(self.url_pasarela, {'accion': 'rechazar'}, follow=True)
        self.assertContains(resp, 'La pasarela rechazó el pago')
        self.assertContains(resp, 'Fallida')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'FALLIDA')
        self.assertNotContains(resp, 'Confirmar pago')

    def test_si_cambio_la_cotizacion_antes_de_pagar_se_cancela_y_queda_para_devolver(self):
        self._operar_y_pedir_pasarela()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        resp = self.client.post(self.url_pasarela, {'accion': 'pagar'}, follow=True)
        self.assertContains(resp, 'cancelada porque la tasa de cambio')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.assertIn('debe devolverse', self.tx.observacion)

    def test_si_vuelve_sin_pagar_puede_retomar_el_pago(self):
        self._operar_y_pedir_pasarela()
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resumen, 'Esperando el pago externo')
        self.assertContains(resumen, self.url_pasarela)  # enlace "Ir a la pasarela para pagar"
        resp = self.client.post(self.url_pasarela, {'accion': 'pagar'}, follow=True)
        self.assertContains(resp, 'Exitosa')

    def test_el_resumen_ofrece_pagar_con_la_pasarela_solo_en_las_compras(self):
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'VENTA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        compra, venta = Transaccion.objects.get(tipo='COMPRA'), Transaccion.objects.get(tipo='VENTA')
        self.assertContains(self.client.get(f'/api/transacciones/gestion/operar/{compra.pk}/'), 'Pagar con la pasarela')
        self.assertNotContains(self.client.get(f'/api/transacciones/gestion/operar/{venta.pk}/'), 'Pagar con la pasarela')


class SeguridadDeLaPasarelaTests(BasePasarelaTests):
    def test_el_aviso_va_firmado_y_lo_acepta_el_mismo_codigo_que_verifica_el_webhook(self):
        self._operar_y_pedir_pasarela()
        capturado = {}
        real = __import__('apps.pasarela.views', fromlist=['x']).procesar_aviso_de_pago

        def espia(cuerpo, firma):
            capturado.update(cuerpo=cuerpo, firma=firma)
            return real(cuerpo, firma)

        with mock.patch('apps.pasarela.views.procesar_aviso_de_pago', espia):
            self.client.post(self.url_pasarela, {'accion': 'pagar'})
        self.assertTrue(webhook.firma_valida(capturado['cuerpo'], capturado['firma']))
        self.assertEqual(
            json.loads(capturado['cuerpo']),
            {'referencia': self.tx.referencia_pago_externo, 'estado': 'PAGADO'},
        )

    def test_sin_secreto_configurado_no_se_confirma_y_se_explica(self):
        self._operar_y_pedir_pasarela()
        with self.settings(WEBHOOK_PAGO_SECRET=''):
            resp = self.client.post(self.url_pasarela, {'accion': 'pagar'}, follow=True)
        self.assertContains(resp, 'No se pudo registrar el pago')
        self.assertContains(resp, 'Firma inválida')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_requiere_login(self):
        self._operar_y_pedir_pasarela()
        self.client.logout()
        self.assertEqual(self.client.get(self.url_pasarela).status_code, 302)
        self.assertEqual(self.client.post(self.url_pasarela, {'accion': 'pagar'}).status_code, 302)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_no_se_puede_pagar_la_operacion_de_otro_cliente(self):
        otro = _cliente(nombre='Otro Cliente', documento='PSR-2')
        ajena = Transaccion.objects.create(
            usuario=Usuario.objects.get(username='final_pasarela'), cliente=otro, moneda=self.moneda,
            metodo_pago=self.medio.metodo_pago, tipo='COMPRA', cantidad=Decimal('1'),
            tasa_cambio=Decimal('7400'), estado='PENDIENTE_PAGO', referencia_pago_externo='PAS-AJENA',
        )
        self.assertEqual(self.client.get('/api/pasarela/pagar/PAS-AJENA/').status_code, 404)
        self.assertEqual(self.client.post('/api/pasarela/pagar/PAS-AJENA/', {'accion': 'pagar'}).status_code, 404)
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, 'PENDIENTE_PAGO')

    def test_referencia_inexistente(self):
        self.assertEqual(self.client.get('/api/pasarela/pagar/PAS-NO-EXISTE/').status_code, 404)

    def test_accion_invalida_no_toca_nada(self):
        self._operar_y_pedir_pasarela()
        resp = self.client.post(self.url_pasarela, {'accion': 'regalame-la-operacion'}, follow=True)
        self.assertContains(resp, 'Elegí Pagar o Rechazar')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_pagar_dos_veces_no_cobra_dos_veces(self):
        """Un doble clic en Pagar: la segunda vez la operación ya no espera un pago."""
        self._operar_y_pedir_pasarela()
        self.client.post(self.url_pasarela, {'accion': 'pagar'})
        resp = self.client.post(self.url_pasarela, {'accion': 'pagar'}, follow=True)
        self.assertContains(resp, 'ya no espera un pago')
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')

    def test_una_operacion_ya_terminada_se_muestra_sin_botones_de_pago(self):
        self._operar_y_pedir_pasarela()
        self.client.post(self.url_pasarela, {'accion': 'pagar'})
        resp = self.client.get(self.url_pasarela)
        self.assertContains(resp, 'ya no espera un pago')
        self.assertNotContains(resp, 'name="accion"')
        self.assertContains(resp, 'Volver a mi operación')


class PasarelaApagadaTests(BasePasarelaTests):
    """Fuera de desarrollo la pasarela simulada no debe poder "pagar" sin pagar."""

    def test_apagada_la_pantalla_no_existe(self):
        self._operar_y_pedir_pasarela()
        url = self.url_pasarela
        with self.settings(PASARELA_SIMULADA_ACTIVA=False):
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {'accion': 'pagar'}).status_code, 404)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_apagada_no_se_inicia_un_pago_que_nadie_podria_hacer(self):
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        tx = Transaccion.objects.get()
        with self.settings(PASARELA_SIMULADA_ACTIVA=False):
            resumen = self.client.get(f'/api/transacciones/gestion/operar/{tx.pk}/')
            self.assertNotContains(resumen, 'Pagar con la pasarela')
            resp = self.client.post(f'/api/transacciones/gestion/operar/{tx.pk}/pago-externo/', follow=True)
            self.assertContains(resp, 'no está habilitada en este ambiente')
        tx.refresh_from_db()
        self.assertEqual((tx.estado, tx.referencia_pago_externo), ('PENDIENTE', None))

    def test_por_defecto_solo_esta_encendida_en_desarrollo(self):
        """Sin la variable de entorno, sigue a DEBUG tal como se cargó la
        configuración (el corredor de tests apaga ``settings.DEBUG`` después)."""
        import sys
        configuracion = sys.modules['config.settings']
        self.assertEqual(configuracion.PASARELA_SIMULADA_ACTIVA, configuracion.DEBUG)
