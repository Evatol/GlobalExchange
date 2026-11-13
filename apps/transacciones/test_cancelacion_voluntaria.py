"""Pruebas de la cancelación voluntaria (E4-195, criterio 2).

Archivo nuevo: apps/transacciones/test_cancelacion_voluntaria.py
Se corre con: python manage.py test apps.transacciones.test_cancelacion_voluntaria
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.divisas.models import Moneda
from apps.transacciones.models import MetodoPago, Transaccion
from apps.usuarios.models import Cliente, Usuario


class CancelacionVoluntariaTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.login = get_user_model().objects.create_user(
            username='cancela_cliente', password='x'
        )
        cls.usuario = Usuario.objects.create(
            username='cancela_cliente', email='cancela@example.com',
            nombres='Ana', apellidos='Prueba', telefono='0', direccion='-',
        )
        cls.cliente = Cliente.objects.create(
            nombre='Ana Prueba', documento='9990001', tipo='FISICA'
        )
        cls.usuario.clientes.add(cls.cliente)
        cls.otro_cliente = Cliente.objects.create(
            nombre='Otro Cliente', documento='9990002', tipo='FISICA'
        )
        cls.moneda = Moneda.objects.create(codigo='XTS', nombre='Moneda de prueba', simbolo='X')
        cls.efectivo = MetodoPago.objects.create(
            nombre='Efectivo prueba', tipo=MetodoPago.TIPO_EFECTIVO
        )

    def setUp(self):
        self.client.force_login(self.login)

    def _transaccion(self, estado='PENDIENTE', cliente=None):
        return Transaccion.objects.create(
            usuario=self.usuario,
            cliente=cliente or self.cliente,
            moneda=self.moneda,
            metodo_pago=self.efectivo,
            tipo='COMPRA',
            cantidad=Decimal('10.00'),
            tasa_cambio=Decimal('7400.000000'),
            monto_total=Decimal('75110.00'),
            estado=estado,
        )

    def _cancelar(self, transaccion, **extra):
        return self.client.post(
            reverse('operacion_cancelar', args=[transaccion.pk]), **extra
        )

    def test_cancelar_una_pendiente_vuelve_a_la_pantalla_inicial(self):
        tx = self._transaccion()
        response = self._cancelar(tx)
        self.assertRedirects(
            response, reverse('operar_divisa'), fetch_redirect_response=False
        )
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')
        mensajes = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any(f'#{tx.pk}' in m for m in mensajes))

    def test_cancelar_una_que_espera_el_pago_externo(self):
        tx = self._transaccion(estado='PENDIENTE_PAGO')
        response = self._cancelar(tx)
        self.assertRedirects(
            response, reverse('operar_divisa'), fetch_redirect_response=False
        )
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')

    def test_no_se_cancela_una_operacion_exitosa(self):
        tx = self._transaccion(estado='EXITOSA')
        response = self._cancelar(tx)
        # Se queda en el detalle de la operación, con el motivo.
        self.assertRedirects(
            response,
            reverse('operacion_detalle', args=[tx.pk]),
            fetch_redirect_response=False,
        )
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')
        mensajes = [m for m in get_messages(response.wsgi_request)]
        self.assertTrue(any(m.level_tag == 'error' for m in mensajes))

    def test_no_se_cancela_una_operacion_ya_pagada_por_la_pasarela(self):
        tx = self._transaccion(estado='PAGADO')
        response = self._cancelar(tx)
        self.assertRedirects(
            response,
            reverse('operacion_detalle', args=[tx.pk]),
            fetch_redirect_response=False,
        )
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'PAGADO')

    def test_no_se_cancela_la_operacion_de_otro_cliente(self):
        tx = self._transaccion(cliente=self.otro_cliente)
        response = self._cancelar(tx)
        self.assertEqual(response.status_code, 404)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'PENDIENTE')

    def test_cancelar_no_pisa_un_pago_ya_confirmado(self):
        tx = self._transaccion(estado='PENDIENTE_PAGO')
        # La pantalla cargó la operación cuando todavía esperaba el pago...
        desactualizada = Transaccion.objects.get(pk=tx.pk)
        # ...y mientras tanto el webhook la confirmó.
        Transaccion.objects.filter(pk=tx.pk).update(estado='EXITOSA')
        with self.assertRaises(ValidationError):
            desactualizada.cancelar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_la_pantalla_inicial_muestra_el_aviso_de_cancelacion(self):
        tx = self._transaccion()
        response = self._cancelar(tx, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'Cancelaste la operación #{tx.pk}')

    def test_las_pendientes_tienen_boton_de_cancelar(self):
        tx = self._transaccion()
        response = self.client.get(reverse('operar_divisa'))
        self.assertContains(response, reverse('operacion_cancelar', args=[tx.pk]))