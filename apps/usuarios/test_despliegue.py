"""Pruebas del despliegue ampliado: el seed es idempotente y deja terminales,
cajas con stock y facturas de ejemplo, y el smoke test detecta las fallas."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase

from apps.caja.models import (
    AsignacionCajero, Billete, Caja, MovimientoBillete, StockBillete, Sucursal,
)
from apps.facturacion.models import Factura
from apps.transacciones.models import Transaccion
from apps.usuarios.management.commands.seed_datos_demo import (
    OPERACIONES_DEMO, TERMINALES,
)
from apps.usuarios.models import Usuario


def _sembrar():
    salida = StringIO()
    call_command('seed_datos_demo', stdout=salida)
    return salida.getvalue()


def _estado_de_los_datos():
    """Conteos de todo lo que el seed puede llegar a duplicar."""
    return {
        'sucursales': Sucursal.objects.count(),
        'cajas': Caja.objects.count(),
        'asignaciones': AsignacionCajero.objects.count(),
        'cajeros': Usuario.objects.count(),
        'billetes': Billete.objects.count(),
        'stock_filas': StockBillete.objects.count(),
        'stock_total': StockBillete.objects.aggregate(t=Sum('cantidad'))['t'],
        'movimientos': MovimientoBillete.objects.count(),
        'transacciones': Transaccion.objects.count(),
        'facturas': Factura.objects.count(),
    }


class SeedIdempotenteTests(TestCase):
    def test_correr_el_seed_dos_veces_no_duplica_nada(self):
        _sembrar()
        despues_de_una = _estado_de_los_datos()
        _sembrar()
        self.assertEqual(_estado_de_los_datos(), despues_de_una)

    def test_correr_el_seed_tres_veces_no_duplica_el_stock(self):
        _sembrar()
        inicial = StockBillete.objects.aggregate(t=Sum('cantidad'))['t']
        _sembrar()
        _sembrar()
        self.assertEqual(StockBillete.objects.aggregate(t=Sum('cantidad'))['t'], inicial)

    def test_crea_las_terminales_con_su_caja_abierta_y_stock_inicial(self):
        _sembrar()
        for nombre, _direccion, username in TERMINALES:
            sucursal = Sucursal.objects.get(nombre=nombre)
            caja = Caja.objects.get(sucursal=sucursal)
            self.assertEqual(caja.estado, 'ABIERTA')
            self.assertEqual(caja.cajero.username, username)
            self.assertTrue(
                AsignacionCajero.objects.filter(
                    sucursal=sucursal, usuario=caja.cajero, estado=True
                ).exists()
            )
            self.assertTrue(StockBillete.objects.filter(caja=caja, cantidad__gt=0).exists())

    def test_cada_terminal_tiene_su_propio_stock(self):
        _sembrar()
        cajas = Caja.objects.filter(estado='ABIERTA')
        self.assertGreaterEqual(cajas.count(), 2)  # la caja demo y la terminal
        for caja in cajas:
            self.assertTrue(StockBillete.objects.filter(caja=caja, cantidad__gt=0).exists())

    def test_crea_las_facturas_de_ejemplo_emitidas(self):
        _sembrar()
        self.assertEqual(Factura.objects.count(), len(OPERACIONES_DEMO))
        for factura in Factura.objects.select_related('transaccion'):
            self.assertEqual(factura.estado, 'EMITIDA')
            self.assertEqual(factura.transaccion.estado, 'EXITOSA')
            self.assertEqual(factura.monto, factura.transaccion.monto_total)
            self.assertGreater(factura.monto, Decimal('0'))

    def test_una_caja_cerrada_no_se_vuelve_a_abrir_ni_a_cargar(self):
        _sembrar()
        caja = Caja.objects.get(sucursal__nombre=TERMINALES[0][0])
        caja.cerrar()
        stock = StockBillete.objects.filter(caja=caja).aggregate(t=Sum('cantidad'))['t']
        _sembrar()
        caja.refresh_from_db()
        self.assertEqual(caja.estado, 'CERRADA')
        self.assertEqual(
            StockBillete.objects.filter(caja=caja).aggregate(t=Sum('cantidad'))['t'], stock
        )


class SmokeTestTests(TestCase):
    def _correr(self, *args):
        salida = StringIO()
        try:
            call_command('verificar_despliegue', *args, stdout=salida)
        except CommandError:
            return salida.getvalue(), True
        return salida.getvalue(), False

    def test_con_los_datos_de_demo_todo_pasa(self):
        _sembrar()
        salida, fallo = self._correr()
        self.assertFalse(fallo, salida)
        self.assertNotIn('FALLA', salida)
        self.assertIn('OK Facturación, PDF', salida)
        self.assertIn('OK Terminal, stock', salida)

    def test_sin_datos_detecta_que_faltan_facturas_y_terminales(self):
        salida, fallo = self._correr()
        self.assertTrue(fallo)
        self.assertIn('FALLA Facturación, datos', salida)
        self.assertIn('FALLA Facturación, PDF', salida)
        self.assertIn('FALLA Terminal, stock', salida)
        # Lo que no depende de los datos sigue pasando.
        self.assertIn('OK Base de datos', salida)

    def test_detecta_una_terminal_sin_billetes(self):
        _sembrar()
        caja = Caja.objects.get(sucursal__nombre=TERMINALES[0][0])
        StockBillete.objects.filter(caja=caja).update(cantidad=0)
        salida, fallo = self._correr()
        self.assertTrue(fallo)
        self.assertIn('FALLA Terminal, stock', salida)
        self.assertIn(TERMINALES[0][0], salida)

    def test_detecta_que_no_hay_facturas_emitidas(self):
        _sembrar()
        Factura.objects.update(estado='ANULADA')
        salida, fallo = self._correr()
        self.assertTrue(fallo)
        self.assertIn('FALLA Facturación, datos', salida)

    def test_la_opcion_sin_datos_no_exige_datos_de_demo(self):
        salida, fallo = self._correr('--sin-datos')
        self.assertFalse(fallo, salida)
        self.assertNotIn('Facturación, datos', salida)

    def test_no_deja_rastros(self):
        from django.contrib.auth import get_user_model
        from django.contrib.sessions.models import Session
        _sembrar()
        sesiones = Session.objects.count()
        self._correr()
        self.assertFalse(get_user_model().objects.filter(username='smoke_test').exists())
        self.assertEqual(Session.objects.count(), sesiones)