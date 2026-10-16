"""Pruebas del stock insuficiente en la terminal (E4-195, criterio 1).

Archivo nuevo: apps/transacciones/test_stock_insuficiente.py
Se corre con: python manage.py test apps.transacciones.test_stock_insuficiente
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.caja.models import Billete, Caja, LimiteStock, StockBillete, Sucursal
from apps.divisas.models import Moneda, TasaCambio
from apps.notificaciones.models import Notificaciones
from apps.transacciones.models import MetodoPago, Transaccion
from apps.usuarios.models import Cliente, Usuario


def _usuario(username):
    return Usuario.objects.create(
        username=username, email=f'{username}@example.com',
        nombres=username, apellidos='Prueba', telefono='0', direccion='-',
    )


class StockInsuficienteEnLaTerminalTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.cliente = Cliente.objects.create(
            nombre='Cliente Terminal', documento='9990101', tipo='FISICA'
        )
        cls.usuario = _usuario('cliente_terminal')
        cls.usuario.clientes.add(cls.cliente)
        cls.efectivo = MetodoPago.objects.create(
            nombre='Efectivo terminal', tipo=MetodoPago.TIPO_EFECTIVO
        )
        cls.sucursal = Sucursal.objects.create(nombre='Sucursal prueba', direccion='-')

        cls.usd = Moneda.objects.create(codigo='XTU', nombre='Dólar de prueba', simbolo='$')
        TasaCambio.objects.create(
            moneda=cls.usd, tasa_compra=Decimal('7000'), tasa_venta=Decimal('7500'),
            origen='prueba',
        )
        cls.billete_usd = Billete.objects.create(moneda=cls.usd, denominacion=Decimal('10'))

        # Quienes tienen que enterarse de una falla.
        get_user_model().objects.create_superuser(
            'admin_terminal', 'admin_terminal@example.com', 'x'
        )
        cls.admin = _usuario('admin_terminal')
        cls.cajero = _usuario('cajero_terminal')

    def _caja(self, cajero, billetes_de_10, estado='ABIERTA'):
        caja = Caja.objects.create(
            sucursal=self.sucursal, cajero=cajero, estado=estado,
            saldo_inicial=Decimal('0'), saldo_actual=Decimal('0'),
        )
        StockBillete.objects.create(caja=caja, billete=self.billete_usd, cantidad=billetes_de_10)
        return caja

    def _operacion(self, tipo='COMPRA', cantidad='100.00', modalidad='DIGITAL', moneda=None):
        moneda = moneda or self.usd
        tasa = moneda.tasas.filter(estado=True).order_by('-fecha_hora').first()
        return Transaccion.objects.create(
            usuario=self.usuario, cliente=self.cliente, moneda=moneda,
            metodo_pago=self.efectivo, tipo=tipo, cantidad=Decimal(cantidad),
            tasa_cambio=tasa.tasa_para(tipo), modalidad=modalidad,
        )

    def test_con_stock_suficiente_la_operacion_se_confirma(self):
        self._caja(self.cajero, 10)  # 100 en billetes de 10
        tx = self._operacion(cantidad='50.00')
        tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_sin_stock_suficiente_queda_fallida_con_mensaje_claro(self):
        self._caja(self.cajero, 3)  # solo 30
        tx = self._operacion(cantidad='100.00')
        with self.assertRaises(ValidationError) as ctx:
            tx.confirmar()
        self.assertIn('no cuenta con billetes suficientes de XTU', ctx.exception.messages[0])
        self.assertIn('quedó registrada como fallida', ctx.exception.messages[0])
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'FALLIDA')
        self.assertIn('billetes suficientes', tx.observacion)

    def test_avisa_a_los_administradores_y_al_cajero(self):
        self._caja(self.cajero, 3)
        tx = self._operacion(cantidad='100.00')
        with self.assertRaises(ValidationError):
            tx.confirmar()
        for destinatario in (self.admin, self.cajero):
            avisos = Notificaciones.objects.filter(usuario=destinatario, tipo='stock_billetes')
            self.assertEqual(avisos.count(), 1)
            self.assertIn(f'#{tx.pk}', avisos.get().mensaje)

    def test_dispara_la_alerta_de_stock_configurada(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('50'))
        self._caja(self.cajero, 3)  # 30 <= 50: alerta BAJA vigente
        tx = self._operacion(cantidad='100.00')
        with self.assertRaises(ValidationError):
            tx.confirmar()
        titulos = list(
            Notificaciones.objects.filter(usuario=self.cajero).values_list('titulo', flat=True)
        )
        self.assertIn('Stock de billetes bajo: XTU', titulos)
        self.assertIn('Operación fallida por falta de billetes: XTU', titulos)

    def test_suma_el_stock_de_todas_las_cajas_abiertas(self):
        self._caja(self.cajero, 6)
        self._caja(_usuario('cajero_terminal_2'), 6)
        tx = self._operacion(cantidad='100.00')  # 10 billetes: no entran en una sola caja
        tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_las_cajas_cerradas_no_cuentan(self):
        self._caja(self.cajero, 20, estado='CERRADA')
        tx = self._operacion(cantidad='100.00')
        with self.assertRaises(ValidationError):
            tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'FALLIDA')

    def test_una_moneda_sin_denominaciones_no_se_evalua(self):
        otra = Moneda.objects.create(codigo='XTN', nombre='Sin billetes', simbolo='N')
        TasaCambio.objects.create(
            moneda=otra, tasa_compra=Decimal('100'), tasa_venta=Decimal('110'),
            origen='prueba',
        )
        tx = self._operacion(moneda=otra)
        tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_las_operaciones_presenciales_no_se_evaluan(self):
        # El cajero ya movió sus propios billetes: no se vuelve a evaluar el stock.
        tx = self._operacion(modalidad='PRESENCIAL')  # sin stock alguno
        tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_una_venta_en_efectivo_entrega_guaranies(self):
        pyg, _ = Moneda.objects.get_or_create(
            codigo='PYG', defaults={'nombre': 'Guaraní', 'simbolo': 'Gs'}
        )
        billete_pyg = Billete.objects.create(moneda=pyg, denominacion=Decimal('10000'))
        caja = self._caja(self.cajero, 20)  # hay divisa, pero casi no hay guaraníes
        StockBillete.objects.create(caja=caja, billete=billete_pyg, cantidad=2)  # 20.000 Gs
        tx = self._operacion(tipo='VENTA', cantidad='10.00')  # hay que entregar ~68.950 Gs
        with self.assertRaises(ValidationError) as ctx:
            tx.confirmar()
        self.assertIn('PYG', ctx.exception.messages[0])
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'FALLIDA')