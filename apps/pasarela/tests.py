"""Tests de las pasarelas de pago (E4-157/E4-158): la simulada y Stripe. El recorrido
del cliente va todo por pantallas, sin comandos. Stripe nunca se llama de verdad: la
librería se reemplaza en cada prueba."""
import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import stripe
from django.conf import settings
from django.template.defaultfilters import floatformat
from django.test import Client, SimpleTestCase, TestCase, override_settings

from apps.banco.models import CuentaBancaria
from apps.divisas.models import Moneda, TasaCambio
from apps.pasarela import stripe_pago
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


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

def _sesion_stripe(id_='cs_test_sesion1', status='open', payment_status='unpaid'):
    """Una sesión de Stripe Checkout, como la devuelve la API."""
    return SimpleNamespace(
        id=id_, status=status, payment_status=payment_status,
        url=f'https://checkout.stripe.com/c/pay/{id_}', payment_intent='pi_test_1',
    )


def _sesion_pagada(id_='cs_test_sesion1'):
    return _sesion_stripe(id_, status='complete', payment_status='paid')


def _aviso_firmado(tipo, sesion, secreto='whsec_falsa'):
    """``(cuerpo, encabezado)`` de un aviso de Stripe firmado como lo firma Stripe:
    HMAC-SHA256 de ``"<t>.<cuerpo>"`` con el secreto del webhook."""
    cuerpo = json.dumps({
        'id': 'evt_test_1', 'object': 'event', 'type': tipo,
        'data': {'object': {
            'id': sesion.id, 'object': 'checkout.session', 'status': sesion.status,
            'payment_status': sesion.payment_status, 'payment_intent': sesion.payment_intent,
        }},
    }).encode()
    marca = int(time.time())
    firma = hmac.new(secreto.encode(), f'{marca}.'.encode() + cuerpo, hashlib.sha256).hexdigest()
    return cuerpo, f't={marca},v1={firma}'


@override_settings(
    PASARELA_PROVEEDOR='stripe', STRIPE_SECRET_KEY='sk_test_falsa',
    STRIPE_WEBHOOK_SECRET='whsec_falsa',
)
class BaseStripeTests(BasePasarelaTests):
    """Lo mismo que ``BasePasarelaTests``, pero con Stripe como pasarela."""

    def _operar(self, tipo='COMPRA', medio=None):
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': tipo, 'moneda_codigo': 'USD', 'cantidad': '10',
            'medio_pago_id': (medio or self.medio).id,
        })
        self.tx = Transaccion.objects.filter(tipo=tipo).latest('pk')
        return self.tx

    def _pagar_con_stripe(self, sesion=None):
        """El cliente compra 10 USD y aprieta "Pagar con Stripe"."""
        self._operar()
        with mock.patch(
            'stripe.checkout.Session.create', return_value=sesion or _sesion_stripe()
        ) as crear:
            resp = self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/pago-externo/')
        self.crear = crear
        self.tx.refresh_from_db()
        return resp

    def _volver_de_stripe(self, sesion):
        """El cliente vuelve de Stripe; Stripe dice que la sesión está así."""
        url = f'/api/pasarela/stripe/retorno/?session_id={self.tx.referencia_pago_externo}'
        with mock.patch('stripe.checkout.Session.retrieve', return_value=sesion) as consultar:
            resp = self.client.get(url, follow=True)
        self.consultar = consultar
        self.tx.refresh_from_db()
        return resp

    def _cancelar(self):
        with mock.patch('stripe.checkout.Session.expire') as expirar:
            self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/cancelar/')
        self.expirar = expirar
        self.tx.refresh_from_db()

    def _medio_efectivo(self):
        return MedioPagoCliente.objects.create(
            cliente=self.cliente, alias='Efectivo', identificador='EFECTIVO',
            metodo_pago=MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO'),
        )


class CobroConStripeTests(BaseStripeTests):
    def test_pagar_con_stripe_crea_la_sesion_y_lleva_al_cliente_a_pagar(self):
        resp = self._pagar_con_stripe()
        self.assertRedirects(
            resp, 'https://checkout.stripe.com/c/pay/cs_test_sesion1', fetch_redirect_response=False
        )
        self.assertEqual(
            (self.tx.estado, self.tx.proveedor_pago, self.tx.referencia_pago_externo),
            ('PENDIENTE_PAGO', 'STRIPE', 'cs_test_sesion1'),
        )
        pedido = self.crear.call_args.kwargs
        self.assertEqual(pedido['api_key'], 'sk_test_falsa')
        self.assertEqual(pedido['mode'], 'payment')
        precio = pedido['line_items'][0]['price_data']
        # 10 x 7.400 = 74.000 + 1,5% = 75.110 guaraníes, sin decimales
        self.assertEqual((precio['currency'], precio['unit_amount']), ('pyg', 75110))
        self.assertEqual(precio['product_data']['name'], 'Compra de 10.00 USD')
        self.assertEqual(pedido['client_reference_id'], str(self.tx.pk))
        self.assertEqual(pedido['metadata'], {'transaccion_id': str(self.tx.pk)})
        self.assertEqual(
            pedido['success_url'],
            'http://testserver/api/pasarela/stripe/retorno/?session_id={CHECKOUT_SESSION_ID}',
        )
        self.assertEqual(
            pedido['cancel_url'], f'http://testserver/api/transacciones/gestion/operar/{self.tx.pk}/'
        )
        # Stripe exige entre 30 minutos y 24 horas de vida para la sesión
        vida = pedido['expires_at'] - time.time()
        self.assertTrue(30 * 60 < vida < 24 * 60 * 60)

    def test_el_resumen_ofrece_pagar_con_stripe_en_vez_de_confirmar(self):
        self._operar()
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resumen, 'Pagar con Stripe')
        self.assertNotContains(resumen, 'Confirmar pago')
        self.assertNotContains(resumen, 'Pagar con la pasarela')

    def test_esperando_a_stripe_el_resumen_deja_retomar_el_pago(self):
        self._pagar_con_stripe()
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resumen, 'Pago con Stripe iniciado')
        self.assertContains(resumen, 'Ir a Stripe para pagar')
        self.assertContains(resumen, '/api/pasarela/pagar/cs_test_sesion1/')

    def test_una_compra_no_efectivo_no_se_confirma_sin_pasar_por_stripe(self):
        self._operar()
        resp = self.client.post(
            f'/api/transacciones/gestion/operar/{self.tx.pk}/confirmar/', follow=True
        )
        self.assertContains(resp, 'se pagan con Stripe')
        api = self.client.post(f'/api/transacciones/transacciones/{self.tx.pk}/confirmar/')
        self.assertEqual(api.status_code, 409)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE')
        self.assertEqual(self._saldo(), Decimal('1000000.00'))  # tampoco se debitó el banco

    def test_el_efectivo_se_sigue_pagando_en_caja(self):
        tx = self._operar(medio=self._medio_efectivo())
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{tx.pk}/')
        self.assertContains(resumen, 'Confirmar pago')
        self.assertNotContains(resumen, 'Stripe')
        with mock.patch('stripe.checkout.Session.create') as crear:
            resp = self.client.post(
                f'/api/transacciones/gestion/operar/{tx.pk}/pago-externo/', follow=True
            )
        self.assertContains(resp, 'no está habilitada en este ambiente')
        crear.assert_not_called()
        self.client.post(f'/api/transacciones/gestion/operar/{tx.pk}/confirmar/')
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_la_venta_sigue_acreditando_en_el_banco(self):
        venta = self._operar('VENTA')
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{venta.pk}/')
        self.assertNotContains(resumen, 'Stripe')
        self.client.post(f'/api/transacciones/gestion/operar/{venta.pk}/confirmar/')
        venta.refresh_from_db()
        self.assertEqual(venta.estado, 'EXITOSA')
        # 10 x 7.300 = 73.000 - 1,5% = 71.905 acreditados
        self.assertEqual(self._saldo(), Decimal('1071905.00'))

    def test_pagar_dos_veces_no_crea_otra_sesion(self):
        self._pagar_con_stripe()
        with mock.patch('stripe.checkout.Session.create') as crear:
            resp = self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/pago-externo/')
        crear.assert_not_called()
        self.assertRedirects(resp, '/api/pasarela/pagar/cs_test_sesion1/', fetch_redirect_response=False)

    def test_un_error_de_stripe_no_deja_la_operacion_esperando(self):
        casos = (
            (stripe.APIConnectionError('sin red'), 'No se pudo conectar con Stripe'),
            (stripe.AuthenticationError('Invalid API Key sk_test_secreta'), 'clave de Stripe configurada'),
            (stripe.InvalidRequestError('monto muy bajo', param='amount'), 'Stripe no aceptó el pedido'),
        )
        self._operar()
        for error, mensaje in casos:
            with self.subTest(mensaje=mensaje), mock.patch(
                'stripe.checkout.Session.create', side_effect=error
            ):
                resp = self.client.post(
                    f'/api/transacciones/gestion/operar/{self.tx.pk}/pago-externo/', follow=True
                )
                self.assertContains(resp, mensaje)
                self.assertNotContains(resp, 'sk_test_secreta')  # nunca se muestra una clave
                self.tx.refresh_from_db()
                self.assertEqual((self.tx.estado, self.tx.referencia_pago_externo), ('PENDIENTE', None))

    def test_api_iniciar_pago_externo_devuelve_la_url_de_stripe(self):
        self._operar()
        with mock.patch('stripe.checkout.Session.create', return_value=_sesion_stripe()):
            resp = self.client.post(
                f'/api/transacciones/transacciones/{self.tx.pk}/iniciar-pago-externo/'
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['url_pago'], 'https://checkout.stripe.com/c/pay/cs_test_sesion1')
        self.assertEqual(resp.json()['referencia_pago_externo'], 'cs_test_sesion1')
        self.assertEqual(resp.json()['estado'], 'PENDIENTE_PAGO')

    def test_api_si_stripe_falla_responde_502(self):
        self._operar()
        with mock.patch('stripe.checkout.Session.create', side_effect=stripe.APIConnectionError('x')):
            resp = self.client.post(
                f'/api/transacciones/transacciones/{self.tx.pk}/iniciar-pago-externo/'
            )
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()['estado'], 'PENDIENTE')


class CancelarConStripeTests(BaseStripeTests):
    def test_cancelar_cierra_la_sesion_para_que_ya_no_se_pueda_pagar(self):
        self._pagar_con_stripe()
        self._cancelar()
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.expirar.assert_called_once()
        self.assertEqual(self.expirar.call_args.args, ('cs_test_sesion1',))

    def test_si_stripe_no_puede_cerrar_la_sesion_la_operacion_se_cancela_igual(self):
        self._pagar_con_stripe()
        with mock.patch('stripe.checkout.Session.expire', side_effect=stripe.APIConnectionError('x')):
            self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/cancelar/')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'CANCELADA')

    def test_cancelar_una_operacion_que_no_inicio_el_pago_no_llama_a_stripe(self):
        self._operar()
        self._cancelar()
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.expirar.assert_not_called()


class VueltaDeStripeTests(BaseStripeTests):
    """El cliente vuelve de la página de Stripe: se confirma por lo que Stripe dice."""

    def test_pagado_la_operacion_queda_exitosa_y_no_se_debita_el_banco(self):
        self._pagar_con_stripe()
        resp = self._volver_de_stripe(_sesion_pagada())
        self.assertRedirects(resp, f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resp, 'Pago confirmado con Stripe')
        self.assertContains(resp, 'Exitosa')
        self.assertEqual(self.tx.estado, 'EXITOSA')
        self.assertEqual(self._saldo(), Decimal('1000000.00'))  # lo cobró Stripe
        self.consultar.assert_called_once()
        self.assertEqual(self.consultar.call_args.args, ('cs_test_sesion1',))  # se le pregunta a Stripe

    def test_si_vuelve_sin_pagar_la_operacion_sigue_esperando(self):
        self._pagar_con_stripe()
        resp = self._volver_de_stripe(_sesion_stripe())
        self.assertContains(resp, 'Todavía no recibimos el pago de Stripe')
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_no_se_confirma_por_lo_que_trae_el_navegador(self):
        self._pagar_con_stripe()
        url = (
            f'/api/pasarela/stripe/retorno/?session_id={self.tx.referencia_pago_externo}'
            '&payment_status=paid&status=complete'
        )
        with mock.patch('stripe.checkout.Session.retrieve', return_value=_sesion_stripe()):
            self.client.get(url)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_volver_dos_veces_no_cobra_dos_veces(self):
        self._pagar_con_stripe()
        self._volver_de_stripe(_sesion_pagada())
        resp = self._volver_de_stripe(_sesion_pagada())
        self.assertContains(resp, 'Pago confirmado con Stripe')
        self.assertEqual(self.tx.estado, 'EXITOSA')
        self.assertEqual(self._saldo(), Decimal('1000000.00'))

    def test_si_cambio_la_cotizacion_se_cancela_y_el_pago_se_devuelve(self):
        self._pagar_con_stripe()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        with mock.patch(
            'stripe.Refund.create', return_value=SimpleNamespace(id='re_test_1')
        ) as reembolsar:
            resp = self._volver_de_stripe(_sesion_pagada())
        self.assertContains(resp, 'cancelada porque la tasa de cambio')
        self.assertContains(resp, 'se te devuelve completo')
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.assertIn('se devolvió al cliente (reembolso re_test_1)', self.tx.observacion)
        self.assertNotIn('debe devolverse', self.tx.observacion)
        reembolsar.assert_called_once_with(
            payment_intent='pi_test_1', idempotency_key='reembolso-cs_test_sesion1',
            api_key='sk_test_falsa',
        )

    def test_si_el_reembolso_falla_queda_anotado_para_devolverlo_a_mano(self):
        self._pagar_con_stripe()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        with mock.patch('stripe.Refund.create', side_effect=stripe.APIConnectionError('x')), \
                self.assertLogs('apps.pasarela.views', level='WARNING'):
            resp = self._volver_de_stripe(_sesion_pagada())
        self.assertContains(resp, 'No se pudo conectar con Stripe')
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.assertIn('debe devolverse', self.tx.observacion)

    def test_la_sesion_de_otro_cliente_no_se_puede_confirmar(self):
        otro = _cliente(nombre='Otro Cliente', documento='PSR-2')
        ajena = Transaccion.objects.create(
            usuario=Usuario.objects.get(username='final_pasarela'), cliente=otro, moneda=self.moneda,
            metodo_pago=self.medio.metodo_pago, tipo='COMPRA', cantidad=Decimal('1'),
            tasa_cambio=Decimal('7400'), estado='PENDIENTE_PAGO',
            referencia_pago_externo='cs_test_ajena', proveedor_pago='STRIPE',
        )
        with mock.patch('stripe.checkout.Session.retrieve') as consultar:
            resp = self.client.get('/api/pasarela/stripe/retorno/?session_id=cs_test_ajena')
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(self.client.get('/api/pasarela/stripe/retorno/').status_code, 404)
        consultar.assert_not_called()
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, 'PENDIENTE_PAGO')

    def test_requiere_login(self):
        self._pagar_con_stripe()
        self.client.logout()
        resp = self.client.get(f'/api/pasarela/stripe/retorno/?session_id={self.tx.referencia_pago_externo}')
        self.assertEqual(resp.status_code, 302)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_si_stripe_no_responde_se_avisa_y_la_operacion_sigue_esperando(self):
        self._pagar_con_stripe()
        url = f'/api/pasarela/stripe/retorno/?session_id={self.tx.referencia_pago_externo}'
        with mock.patch('stripe.checkout.Session.retrieve', side_effect=stripe.APIConnectionError('x')), \
                self.assertLogs('apps.pasarela.views', level='WARNING'):
            resp = self.client.get(url, follow=True)
        self.assertContains(resp, 'No se pudo conectar con Stripe')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')


class RetomarElPagoConStripeTests(BaseStripeTests):
    """``/api/pasarela/pagar/<referencia>/`` de una operación de Stripe."""

    def _abrir(self, sesion):
        with mock.patch('stripe.checkout.Session.retrieve', return_value=sesion):
            resp = self.client.get(f'/api/pasarela/pagar/{self.tx.referencia_pago_externo}/', follow=False)
        self.tx.refresh_from_db()
        return resp

    def test_si_la_sesion_sigue_abierta_lleva_a_la_pagina_de_stripe(self):
        self._pagar_con_stripe()
        resp = self._abrir(_sesion_stripe())
        self.assertRedirects(
            resp, 'https://checkout.stripe.com/c/pay/cs_test_sesion1', fetch_redirect_response=False
        )

    def test_si_la_sesion_vencio_la_operacion_queda_fallida(self):
        self._pagar_con_stripe()
        resp = self._abrir(_sesion_stripe(status='expired'))
        self.assertRedirects(
            resp, f'/api/transacciones/gestion/operar/{self.tx.pk}/', fetch_redirect_response=False
        )
        self.assertEqual(self.tx.estado, 'FALLIDA')
        self.assertIn('venció', self.tx.observacion)

    def test_una_operacion_que_ya_no_espera_el_pago_no_lleva_a_stripe(self):
        self._pagar_con_stripe()
        self._cancelar()
        with mock.patch('stripe.checkout.Session.retrieve') as consultar:
            resp = self.client.get(f'/api/pasarela/pagar/{self.tx.referencia_pago_externo}/', follow=True)
        consultar.assert_not_called()
        self.assertContains(resp, 'ya no espera un pago')

    def test_no_se_llega_a_la_sesion_de_otro_cliente(self):
        self.assertEqual(self.client.get('/api/pasarela/pagar/cs_test_no_existe/').status_code, 404)


class WebhookDeStripeTests(BaseStripeTests):
    """Los avisos de Stripe, firmados como los firma Stripe (se verifica de verdad)."""

    URL = '/api/pasarela/stripe/webhook/'

    def setUp(self):
        super().setUp()
        # Stripe no tiene sesión ni CSRF: el cliente de pruebas lo comprueba.
        self.stripe = Client(enforce_csrf_checks=True, raise_request_exception=False)
        self._pagar_con_stripe()

    def _aviso(self, tipo, sesion=None, firma=None, secreto='whsec_falsa'):
        cuerpo, encabezado = _aviso_firmado(tipo, sesion or _sesion_pagada(), secreto)
        return self.stripe.post(
            self.URL, data=cuerpo, content_type='application/json',
            HTTP_STRIPE_SIGNATURE=encabezado if firma is None else firma,
        )

    def test_el_pago_completado_confirma_la_operacion(self):
        resp = self._aviso('checkout.session.completed')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {'detail': 'Aviso procesado.', 'evento': 'PAGADO'})
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'EXITOSA')
        self.assertEqual(self._saldo(), Decimal('1000000.00'))

    def test_el_pago_de_un_medio_asincrono_confirma_cuando_se_acredita(self):
        sin_acreditar = _sesion_stripe(status='complete', payment_status='unpaid')
        self.assertEqual(self._aviso('checkout.session.completed', sin_acreditar).json()['evento'], None)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')
        self._aviso('checkout.session.async_payment_succeeded')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'EXITOSA')

    def test_repetir_el_aviso_no_cobra_dos_veces(self):
        self._aviso('checkout.session.completed')
        resp = self._aviso('checkout.session.completed')
        self.assertEqual(resp.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'EXITOSA')
        self.assertEqual(self._saldo(), Decimal('1000000.00'))

    def test_la_sesion_vencida_deja_la_operacion_fallida(self):
        resp = self._aviso('checkout.session.expired', _sesion_stripe(status='expired'))
        self.assertEqual(resp.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'FALLIDA')
        self.assertIn('venció', self.tx.observacion)

    def test_el_pago_asincrono_fallido_deja_la_operacion_fallida(self):
        sesion = _sesion_stripe(status='complete', payment_status='unpaid')
        self._aviso('checkout.session.async_payment_failed', sesion)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'FALLIDA')
        self.assertIn('no pudo cobrar', self.tx.observacion)

    def test_un_aviso_de_vencimiento_de_una_operacion_cancelada_no_la_toca(self):
        self._cancelar()
        resp = self._aviso('checkout.session.expired', _sesion_stripe(status='expired'))
        self.assertEqual(resp.status_code, 200)  # no se reintenta
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'CANCELADA')

    def test_sin_firma_valida_no_se_toca_nada(self):
        casos = {
            'sin firma': '',
            'firma de otro secreto': _aviso_firmado('checkout.session.completed', _sesion_pagada(), 'otro')[1],
            'firma inventada': 't=1,v1=abc',
        }
        for nombre, firma in casos.items():
            with self.subTest(nombre):
                resp = self._aviso('checkout.session.completed', firma=firma)
                self.assertEqual(resp.status_code, 400)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_el_cuerpo_alterado_invalida_la_firma(self):
        cuerpo, encabezado = _aviso_firmado('checkout.session.completed', _sesion_pagada())
        resp = self.stripe.post(
            self.URL, data=cuerpo.replace(b'paid', b'unpaid '), content_type='application/json',
            HTTP_STRIPE_SIGNATURE=encabezado,
        )
        self.assertEqual(resp.status_code, 400)

    def test_sin_secreto_de_webhook_configurado_responde_503(self):
        with self.settings(STRIPE_WEBHOOK_SECRET=''):
            resp = self._aviso('checkout.session.completed')
        self.assertEqual(resp.status_code, 503)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_los_avisos_que_no_son_de_pago_o_de_otra_sesion_se_ignoran_con_200(self):
        self.assertEqual(self._aviso('payment_intent.created').status_code, 200)
        ajena = _sesion_pagada('cs_test_de_otro_sistema')
        resp = self._aviso('checkout.session.completed', ajena)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ignorado', resp.json()['detail'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_solo_acepta_post(self):
        self.assertEqual(self.stripe.get(self.URL).status_code, 405)

    def test_si_pago_despues_de_cancelar_el_pago_se_devuelve(self):
        self._cancelar()
        with mock.patch(
            'stripe.Refund.create', return_value=SimpleNamespace(id='re_test_9')
        ) as reembolsar:
            resp = self._aviso('checkout.session.completed')
            self._aviso('checkout.session.completed')  # Stripe reintenta: no duplica la nota
        self.assertEqual(resp.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'CANCELADA')  # no revive
        self.assertEqual(self.tx.observacion.count('re_test_9'), 1)
        self.assertIn('se devolvió al cliente', self.tx.observacion)
        self.assertEqual(reembolsar.call_args.kwargs['idempotency_key'], 'reembolso-cs_test_sesion1')

    def test_si_el_reembolso_falla_responde_error_para_que_stripe_reintente(self):
        self._cancelar()
        with mock.patch('stripe.Refund.create', side_effect=stripe.APIConnectionError('x')):
            resp = self._aviso('checkout.session.completed')
        self.assertEqual(resp.status_code, 500)
        self.tx.refresh_from_db()
        self.assertIn('debe devolverse', self.tx.observacion)


class ModeloConStripeTests(BaseStripeTests):
    def test_requiere_pasarela_solo_en_compras_no_efectivo_con_stripe_activo(self):
        compra = self._operar()
        venta = self._operar('VENTA')
        efectivo = self._operar(medio=self._medio_efectivo())
        self.assertTrue(compra.requiere_pasarela)
        self.assertFalse(venta.requiere_pasarela)
        self.assertFalse(efectivo.requiere_pasarela)
        with self.settings(PASARELA_PROVEEDOR='simulada'):
            self.assertFalse(compra.requiere_pasarela)

    def test_no_se_inicia_el_pago_con_stripe_de_una_compra_en_efectivo(self):
        from django.core.exceptions import ValidationError
        efectivo = self._operar(medio=self._medio_efectivo())
        with self.assertRaisesMessage(ValidationError, 'El efectivo se paga en caja'):
            efectivo.validar_pago_externo(Transaccion.PROVEEDOR_STRIPE)

    def test_anotar_devolucion_reemplaza_el_aviso_de_que_debe_devolverse(self):
        self._pagar_con_stripe()
        self.tx.observacion = 'Cambió la cotización: el pago externo cs_test_sesion1 debe devolverse al cliente.'
        self.tx.anotar_devolucion('re_1')
        self.tx.anotar_devolucion('re_1')  # repetirlo no cambia nada
        self.assertEqual(
            self.tx.observacion,
            'Cambió la cotización: el pago externo cs_test_sesion1 se devolvió al cliente (reembolso re_1).',
        )

    def test_anotar_devolucion_en_una_operacion_sin_observacion(self):
        self._pagar_con_stripe()
        self.tx.anotar_devolucion('re_2')
        self.assertEqual(
            self.tx.observacion,
            'El pago externo cs_test_sesion1 se devolvió al cliente (reembolso re_2).',
        )

    def test_anotar_que_debe_devolverse_no_se_duplica_ni_pisa_una_devolucion_hecha(self):
        self._pagar_con_stripe()
        self.tx.anotar_devolucion()
        self.tx.anotar_devolucion()
        self.assertEqual(self.tx.observacion.count('debe devolverse'), 1)
        self.tx.anotar_devolucion('re_3')
        self.tx.anotar_devolucion()
        self.assertNotIn('debe devolverse', self.tx.observacion)
        self.assertEqual(self.tx.observacion.count('re_3'), 1)
        self.tx.refresh_from_db()
        self.assertIn('re_3', self.tx.observacion)  # quedó guardado


class StripePagoTests(SimpleTestCase):
    """La capa fina sobre la librería de Stripe."""

    def test_las_pruebas_nunca_hablan_con_stripe(self):
        self.assertEqual(settings.PASARELA_PROVEEDOR, 'simulada')
        self.assertEqual(settings.STRIPE_SECRET_KEY, '')
        self.assertFalse(stripe_pago.activa())

    def test_el_monto_va_en_guaranies_enteros(self):
        for monto, esperado in (
            ('75110.00', 75110), ('75110.49', 75110), ('75110.50', 75111),
            (Decimal('100000.00'), 100000), (Decimal('0.50'), 1),
        ):
            with self.subTest(monto=monto):
                self.assertEqual(stripe_pago.monto_en_unidades(monto), esperado)

    def test_sin_clave_secreta_no_se_llama_a_stripe(self):
        with mock.patch('stripe.checkout.Session.retrieve') as consultar:
            with self.assertRaisesMessage(stripe_pago.ErrorStripe, 'no está configurado'):
                stripe_pago.obtener_sesion('cs_test_x')
        consultar.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='sk_test_falsa')
    def test_los_errores_de_stripe_se_traducen_sin_filtrar_la_clave(self):
        with mock.patch(
            'stripe.checkout.Session.retrieve',
            side_effect=stripe.AuthenticationError('Invalid API Key provided: sk_test_falsa'),
        ):
            with self.assertRaises(stripe_pago.ErrorStripe) as ctx:
                stripe_pago.obtener_sesion('cs_test_x')
        self.assertNotIn('sk_test', str(ctx.exception))

    @override_settings(PASARELA_PROVEEDOR='stripe')
    def test_activa_sigue_a_la_configuracion(self):
        self.assertTrue(stripe_pago.activa())
