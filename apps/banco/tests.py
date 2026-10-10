from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.usuarios.models import Cliente, Usuario

from . import services
from .models import CuentaBancaria, MovimientoBancario


def _usuario_con_rol(username, rol=None):
    user = User.objects.create_user(username)
    if rol:
        grupo, _ = Group.objects.get_or_create(name=rol)
        user.groups.add(grupo)
    return user


def _cuenta(numero='CA-1', tipo=CuentaBancaria.TIPO_CUENTA, documento='80012345-6',
            saldo=Decimal('100000.00'), linea=Decimal('0.00')):
    return services.abrir_cuenta(
        numero=numero, tipo=tipo, entidad='Banco Itaú',
        titular_documento=documento, titular_nombre='Comercial Uno',
        saldo=saldo, linea_credito=linea,
    )


class CuentaBancariaModelTests(TestCase):
    """Reglas de las cuentas: saldo no negativo y línea solo en tarjetas."""

    def test_tarjeta_sin_linea_de_credito_es_invalida(self):
        cuenta = CuentaBancaria(
            numero='T1', tipo=CuentaBancaria.TIPO_TARJETA_CREDITO, entidad='X',
            titular_documento='1', titular_nombre='A',
        )
        with self.assertRaises(ValidationError) as ctx:
            cuenta.full_clean()
        self.assertIn('linea_credito', ctx.exception.message_dict)

    def test_solo_las_tarjetas_tienen_linea_de_credito(self):
        cuenta = CuentaBancaria(
            numero='C1', tipo=CuentaBancaria.TIPO_CUENTA, entidad='X',
            titular_documento='1', titular_nombre='A', linea_credito=Decimal('10'),
        )
        with self.assertRaises(ValidationError) as ctx:
            cuenta.full_clean()
        self.assertIn('linea_credito', ctx.exception.message_dict)

    def test_saldo_negativo_es_invalido(self):
        cuenta = CuentaBancaria(
            numero='C2', tipo=CuentaBancaria.TIPO_CUENTA, entidad='X',
            titular_documento='1', titular_nombre='A', saldo=Decimal('-1'),
        )
        with self.assertRaises(ValidationError):
            cuenta.full_clean()


class ServiciosBancoTests(TestCase):
    """``apps.banco.services``: lo único que mueve saldos."""

    def test_abrir_cuenta_registra_el_saldo_inicial(self):
        cuenta = _cuenta(saldo=Decimal('50000.00'))
        movimiento = cuenta.movimientos.get()
        self.assertEqual(movimiento.tipo, MovimientoBancario.CREDITO)
        self.assertEqual(movimiento.monto, Decimal('50000.00'))
        self.assertEqual(movimiento.concepto, 'Saldo inicial')

    def test_una_tarjeta_arranca_con_toda_su_linea_disponible(self):
        tarjeta = _cuenta(
            numero='TC-1', tipo=CuentaBancaria.TIPO_TARJETA_CREDITO,
            saldo=Decimal('999'), linea=Decimal('500000.00'),
        )
        self.assertEqual(tarjeta.saldo, Decimal('500000.00'))
        self.assertEqual(tarjeta.credito_usado, Decimal('0.00'))

    def test_debitar_descuenta_y_registra_el_movimiento(self):
        _cuenta(saldo=Decimal('100000.00'))
        movimiento = services.debitar('CA-1', Decimal('30000.50'), 'Compra', 'GE-OP-1')
        cuenta = CuentaBancaria.objects.get(numero='CA-1')
        self.assertEqual(cuenta.saldo, Decimal('69999.50'))
        self.assertEqual(movimiento.tipo, MovimientoBancario.DEBITO)
        self.assertEqual(movimiento.saldo_resultante, Decimal('69999.50'))
        self.assertEqual(movimiento.referencia, 'GE-OP-1')

    def test_debitar_sin_saldo_suficiente_no_toca_nada(self):
        _cuenta(saldo=Decimal('1000.00'))
        with self.assertRaises(services.SaldoInsuficiente) as ctx:
            services.debitar('CA-1', Decimal('1000.01'), 'Compra')
        self.assertEqual(str(ctx.exception), 'Saldo insuficiente para pagar 1.000,01 Gs.')
        self.assertNotIn('1.000,00', str(ctx.exception))  # no revela el saldo
        cuenta = CuentaBancaria.objects.get(numero='CA-1')
        self.assertEqual(cuenta.saldo, Decimal('1000.00'))
        self.assertEqual(cuenta.movimientos.count(), 1)  # solo el saldo inicial

    def test_la_tarjeta_baja_su_disponible_hasta_agotar_la_linea(self):
        _cuenta(numero='TC-1', tipo=CuentaBancaria.TIPO_TARJETA_CREDITO, linea=Decimal('100000'))
        services.debitar('TC-1', Decimal('60000'), 'Compra 1')
        services.debitar('TC-1', Decimal('40000'), 'Compra 2')
        tarjeta = CuentaBancaria.objects.get(numero='TC-1')
        self.assertEqual(tarjeta.saldo, Decimal('0.00'))
        self.assertEqual(tarjeta.credito_usado, Decimal('100000.00'))
        with self.assertRaises(services.SaldoInsuficiente):
            services.debitar('TC-1', Decimal('1'), 'Compra 3')

    def test_el_pago_de_tarjeta_no_puede_superar_lo_usado(self):
        _cuenta(numero='TC-1', tipo=CuentaBancaria.TIPO_TARJETA_CREDITO, linea=Decimal('100000'))
        services.debitar('TC-1', Decimal('30000'), 'Compra')
        with self.assertRaises(services.ErrorBancario):
            services.acreditar('TC-1', Decimal('30001'), 'Pago de tarjeta')
        services.acreditar('TC-1', Decimal('30000'), 'Pago de tarjeta')
        self.assertEqual(CuentaBancaria.objects.get(numero='TC-1').saldo, Decimal('100000.00'))

    def test_cuenta_inexistente_o_inactiva(self):
        with self.assertRaises(services.CuentaNoDisponible):
            services.debitar('NO-EXISTE', Decimal('1'), 'x')
        _cuenta().desactivar()
        with self.assertRaises(services.CuentaNoDisponible):
            services.acreditar('CA-1', Decimal('1'), 'x')

    def test_monto_debe_ser_positivo(self):
        _cuenta()
        for monto in (Decimal('0'), Decimal('-5')):
            with self.subTest(monto=monto), self.assertRaises(services.ErrorBancario):
                services.debitar('CA-1', monto, 'x')

    def test_verificar_titular(self):
        _cuenta(documento='80012345-6')
        self.assertIsNone(
            services.verificar_titular('CA-1', CuentaBancaria.TIPO_CUENTA, '80012345-6')
        )
        self.assertIn('no está a nombre', services.verificar_titular(
            'CA-1', CuentaBancaria.TIPO_CUENTA, 'OTRO'
        ))
        self.assertIn('no coincide', services.verificar_titular(
            'CA-1', CuentaBancaria.TIPO_BILLETERA, '80012345-6'
        ))
        self.assertIn('no tiene una cuenta activa', services.verificar_titular(
            'X', CuentaBancaria.TIPO_CUENTA, '80012345-6'
        ))

    def test_formatear_guaranies(self):
        self.assertEqual(services.formatear_guaranies(Decimal('96681.5')), '96.681,50 Gs')


class CuentaBancariaAPITests(APITestCase):
    """``/api/banco/cuentas/``: el administrador gestiona y el analista
    consulta. El usuario final no tiene acceso: la casa de cambio no le
    muestra saldos bancarios. Debitar no está expuesto."""

    def setUp(self):
        self.url = '/api/banco/cuentas/'
        self.cliente = Cliente.objects.create(nombre='Comercial Uno', documento='80012345-6', tipo='FISICA')
        self.propia = _cuenta(numero='CA-1', documento='80012345-6')
        self.ajena = _cuenta(numero='CA-2', documento='999')

        self.user_final = _usuario_con_rol('final_banco', rol='usuario_final')
        usuario = Usuario.objects.create(
            username='final_banco', email='fb@example.com', nombres='F', apellidos='B',
        )
        usuario.clientes.add(self.cliente)

    def test_administrador_abre_una_cuenta(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_banco', rol='administrador'))
        resp = self.client.post(self.url, {
            'numero': 'BI-1', 'tipo': 'BILLETERA', 'entidad': 'Tigo Money',
            'titular_documento': '80012345-6', 'titular_nombre': 'Comercial Uno',
            'saldo': '20000.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(CuentaBancaria.objects.get(numero='BI-1').movimientos.count(), 1)

    def test_tarjeta_sin_linea_se_rechaza(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_banco2', rol='administrador'))
        resp = self.client.post(self.url, {
            'numero': 'TC-9', 'tipo': 'TARJETA_CREDITO', 'entidad': 'Visa',
            'titular_documento': '1', 'titular_nombre': 'A',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('linea_credito', resp.data)

    def test_el_saldo_no_se_edita_directamente(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_banco3', rol='administrador'))
        resp = self.client.patch(f'{self.url}{self.propia.pk}/', {'saldo': '9999999'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.propia.refresh_from_db()
        self.assertEqual(self.propia.saldo, Decimal('100000.00'))

    def test_administrador_carga_saldo(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_banco4', rol='administrador'))
        resp = self.client.post(f'{self.url}{self.propia.pk}/cargar/', {'monto': '5000'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(Decimal(resp.data['saldo']), Decimal('105000.00'))

    def test_usuario_final_no_ve_el_banco_ni_siquiera_sus_cuentas(self):
        self.client.force_authenticate(user=self.user_final)
        for url in (self.url, f'{self.url}{self.propia.pk}/', f'{self.url}{self.propia.pk}/movimientos/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_analista_ve_los_movimientos(self):
        services.debitar('CA-1', Decimal('1000'), 'Compra', 'GE-OP-7')
        self.client.force_authenticate(user=_usuario_con_rol('analista_mov', rol='analista'))
        resp = self.client.get(f'{self.url}{self.propia.pk}/movimientos/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data[0]['referencia'], 'GE-OP-7')

    def test_usuario_final_no_puede_cargarse_saldo(self):
        self.client.force_authenticate(user=self.user_final)
        resp = self.client.post(f'{self.url}{self.propia.pk}/cargar/', {'monto': '5000'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.propia.refresh_from_db()
        self.assertEqual(self.propia.saldo, Decimal('100000.00'))

    def test_analista_consulta_pero_no_modifica(self):
        self.client.force_authenticate(user=_usuario_con_rol('analista_banco', rol='analista'))
        self.assertEqual(self.client.get(self.url).data['count'], 2)
        resp = self.client.post(f'{self.url}{self.propia.pk}/cargar/', {'monto': '5000'})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_no_existe_un_endpoint_para_debitar(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_banco5', rol='administrador'))
        resp = self.client.post(f'{self.url}{self.propia.pk}/debitar/', {'monto': '5000'})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonimo_no_tiene_acceso(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)


class GestionCuentasViewTests(TestCase):
    """Pantalla propia del banco simulado."""

    def setUp(self):
        self.url = '/api/banco/gestion/cuentas/'
        self.cliente = Cliente.objects.create(nombre='Comercial Uno', documento='80012345-6', tipo='FISICA')

    def test_prohibido_para_usuario_final(self):
        self.client.force_login(_usuario_con_rol('final_gc', rol='usuario_final'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_abre_una_tarjeta_para_un_cliente(self):
        self.client.force_login(_usuario_con_rol('admin_gc', rol='administrador'))
        resp = self.client.post(self.url, {
            'cliente': self.cliente.pk, 'tipo': 'TARJETA_CREDITO', 'numero': '4111',
            'entidad': 'Visa', 'saldo': '0', 'linea_credito': '300000',
        }, follow=True)
        self.assertContains(resp, 'Cuenta 4111 abierta.')
        tarjeta = CuentaBancaria.objects.get(numero='4111')
        self.assertEqual(tarjeta.titular_documento, '80012345-6')
        self.assertEqual(tarjeta.saldo, Decimal('300000.00'))

    def test_administrador_carga_saldo_y_ve_los_movimientos(self):
        cuenta = _cuenta(saldo=Decimal('0'))
        self.client.force_login(_usuario_con_rol('admin_gc2', rol='administrador'))
        self.client.post(f'{self.url}{cuenta.pk}/cargar/', {'monto': '25000'})
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.saldo, Decimal('25000.00'))
        resp = self.client.get(f'{self.url}{cuenta.pk}/')
        self.assertContains(resp, 'Carga de saldo')

    def test_analista_ve_las_cuentas_pero_no_puede_abrir(self):
        _cuenta()
        self.client.force_login(_usuario_con_rol('analista_gc', rol='analista'))
        resp = self.client.get(self.url)
        self.assertContains(resp, 'CA-1')
        self.assertNotContains(resp, 'Abrir cuenta')
        resp = self.client.post(self.url, {'cliente': self.cliente.pk, 'tipo': 'CUENTA', 'numero': 'X'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(CuentaBancaria.objects.filter(numero='X').exists())
