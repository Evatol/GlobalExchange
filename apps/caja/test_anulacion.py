"""Tests de E4-196: anular una operación en efectivo. Se revierten los billetes y el
stock de la caja, y el cajero lo hace desde "Mi caja" (no desde la zona de clientes, a
la que el rol cajero no tiene acceso)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.transacciones.models import MetodoPago, Transaccion

from . import services
from .models import AsignacionCajero, Caja, StockBillete
from .test_cierre_movimientos import BaseCajaPresencialTests
from .test_sucursales import _cajero, _login_con_rol

User = get_user_model()


def _url_anular(transaccion):
    return reverse('caja_operacion_anular', args=[transaccion.pk])


class BaseAnulacionTests(BaseCajaPresencialTests):
    def stock(self):
        """El stock completo de la caja: ``{billete_id: cantidad}``."""
        return dict(StockBillete.objects.filter(caja=self.caja).values_list('billete_id', 'cantidad'))

    def otra_caja_abierta(self):
        """La caja de otro cajero de la misma sucursal, abierta y con billetes."""
        otro = _cajero('otro_caj')
        AsignacionCajero.objects.create(sucursal=self.sucursal, usuario=otro)
        caja = Caja.objects.create(sucursal=self.sucursal, cajero=otro, saldo_inicial=0, saldo_actual=0)
        services.abrir_caja(caja, otro, self.carga_inicial())
        return otro, caja


class AnularOperacionEnEfectivoTests(BaseAnulacionTests):
    def test_anular_una_compra_deja_el_stock_como_antes(self):
        antes = self.stock()
        operacion = self.operar(tipo='COMPRA', cantidad=Decimal('100'))
        self.assertNotEqual(self.stock(), antes)  # la operación movió billetes

        anulada = services.anular_operacion_en_efectivo(self.caja, operacion.pk)

        operacion.refresh_from_db()
        self.assertEqual((anulada.pk, operacion.estado), (operacion.pk, 'ANULADA'))
        self.assertIn('anulada', operacion.observacion)
        self.assertEqual(self.stock(), antes)

    def test_anular_una_venta_deja_el_stock_como_antes(self):
        antes = self.stock()
        operacion = self.operar(tipo='VENTA', cantidad=Decimal('100'))
        services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(self.stock(), antes)

    def test_anular_un_cambio_entre_divisas_deja_el_stock_como_antes(self):
        antes = self.stock()
        operacion = self.operar(tipo='CAMBIO', moneda_codigo='USD', moneda_destino_codigo='EUR')
        self.assertNotEqual(self.stock(), antes)
        services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(self.stock(), antes)

    def test_no_se_anula_dos_veces_ni_se_devuelve_el_stock_dos_veces(self):
        operacion = self.operar()
        services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        despues = self.stock()
        with self.assertRaisesMessage(ValidationError, 'ya fue anulada'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(self.stock(), despues)

    def test_solo_se_anulan_las_operaciones_exitosas(self):
        operacion = self.operar()
        Transaccion.objects.filter(pk=operacion.pk).update(estado='FALLIDA')
        with self.assertRaisesMessage(ValidationError, 'Solo se pueden anular transacciones exitosas'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)

    def test_no_se_anula_una_operacion_que_no_es_en_efectivo(self):
        operacion = self.operar()
        transferencia = MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA')
        Transaccion.objects.filter(pk=operacion.pk).update(metodo_pago=transferencia)
        with self.assertRaisesMessage(ValidationError, 'pagadas en efectivo'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')

    def test_con_la_caja_cerrada_no_se_anula_y_no_cambia_nada(self):
        operacion = self.operar()
        services.cerrar_caja(self.caja, self.cajero)
        self.caja.refresh_from_db()
        stock = self.stock()
        with self.assertRaisesMessage(ValidationError, 'cerrada'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')
        self.assertEqual(self.stock(), stock)

    def test_si_ya_no_quedan_los_billetes_a_devolver_no_se_toca_nada(self):
        """En una compra de USD el cliente paga guaraníes y se lleva dólares. Si esos
        guaraníes ya no están en la caja, no se pueden devolver y la anulación se
        rechaza entera, sin reingresar tampoco los dólares."""
        operacion = self.operar(tipo='COMPRA', cantidad=Decimal('100'))
        StockBillete.objects.filter(caja=self.caja, billete__moneda=self.pyg).update(cantidad=0)
        stock = self.stock()
        with self.assertRaisesMessage(ValidationError, 'Stock insuficiente'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')
        self.assertEqual(self.stock(), stock)

    def test_una_operacion_sin_movimientos_de_caja_no_se_puede_anular(self):
        operacion = self.operar()
        with self.assertRaisesMessage(ValidationError, 'No existe esa operación en tu caja'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk + 999)
        sin_movimientos = Transaccion.objects.get(pk=operacion.pk)
        sin_movimientos.movimientos_billetes.all().delete()
        with self.assertRaisesMessage(ValidationError, 'No existe esa operación en tu caja'):
            services.anular_operacion_en_efectivo(self.caja, operacion.pk)

    def test_otra_caja_no_puede_anularla(self):
        operacion = self.operar()
        _, otra_caja = self.otra_caja_abierta()
        stock = self.stock()
        with self.assertRaisesMessage(ValidationError, 'No existe esa operación en tu caja'):
            services.anular_operacion_en_efectivo(otra_caja, operacion.pk)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')
        self.assertEqual(self.stock(), stock)

    def test_la_lista_de_operaciones_de_la_caja_trae_las_mas_recientes_primero(self):
        primera = self.operar(cantidad=Decimal('10'))
        segunda = self.operar(cantidad=Decimal('20'))
        _, otra_caja = self.otra_caja_abierta()
        self.assertEqual([o.pk for o in services.operaciones_de_la_caja(self.caja)], [segunda.pk, primera.pk])
        self.assertEqual(services.operaciones_de_la_caja(otra_caja), [])


class AnularDesdeMiCajaTests(BaseAnulacionTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.login)  # el cajero

    def test_mi_caja_lista_las_operaciones_con_el_boton_de_anular(self):
        operacion = self.operar(tipo='COMPRA', cantidad=Decimal('100'))
        resp = self.client.get(reverse('mi_caja'))
        self.assertContains(resp, 'Últimas operaciones')
        self.assertContains(resp, f'#{operacion.pk} · Compra USD')
        self.assertContains(resp, 'Cliente VIP')
        self.assertContains(resp, _url_anular(operacion))

    def test_el_cajero_anula_la_operacion_y_ve_el_resultado(self):
        antes = self.stock()
        operacion = self.operar()
        resp = self.client.post(_url_anular(operacion), follow=True)
        self.assertRedirects(resp, reverse('mi_caja'))
        self.assertContains(resp, f'Operación #{operacion.pk} anulada')
        self.assertContains(resp, 'Anulada')  # el estado en la lista
        self.assertNotContains(resp, _url_anular(operacion))  # ya no se puede anular de nuevo
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'ANULADA')
        self.assertEqual(self.stock(), antes)

    def test_anular_de_nuevo_muestra_el_motivo(self):
        operacion = self.operar()
        self.client.post(_url_anular(operacion))
        resp = self.client.post(_url_anular(operacion), follow=True)
        self.assertContains(resp, 'ya fue anulada')

    def test_es_solo_por_post(self):
        operacion = self.operar()
        self.assertEqual(self.client.get(_url_anular(operacion)).status_code, 405)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')

    def test_otro_cajero_no_puede_anular_la_operacion_de_esta_caja(self):
        operacion = self.operar()
        otro, _ = self.otra_caja_abierta()
        self.client.force_login(User.objects.get(username=otro.username))
        resp = self.client.post(_url_anular(operacion), follow=True)
        self.assertContains(resp, 'No existe esa operación en tu caja')
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')

    def test_sin_caja_abierta_no_se_anula(self):
        operacion = self.operar()
        services.cerrar_caja(self.caja, self.cajero)
        resp = self.client.post(_url_anular(operacion), follow=True)
        self.assertContains(resp, 'No tenés una caja abierta')
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')

    def test_quien_no_es_cajero_no_puede_anular(self):
        operacion = self.operar()
        for rol in ('usuario_final', 'administrador', 'analista'):
            with self.subTest(rol=rol):
                cliente_http = Client()
                cliente_http.force_login(_login_con_rol(f'sin_caja_{rol}', rol))
                self.assertEqual(cliente_http.post(_url_anular(operacion)).status_code, 403)
        self.assertEqual(Client().post(_url_anular(operacion)).status_code, 302)  # sin login
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'EXITOSA')

    def test_los_accesos_de_anulacion_de_la_zona_de_clientes_ya_no_existen(self):
        """Estaban bajo /api/transacciones/, donde el cajero no puede entrar, y dejaban
        que un cliente anulara su propia operación en efectivo."""
        anonimo = Client()
        self.assertEqual(anonimo.post('/api/transacciones/gestion/operar/1/anular/').status_code, 404)
        self.assertEqual(anonimo.post('/api/transacciones/transacciones/1/anular/').status_code, 404)

    def test_el_historial_muestra_la_operacion_anulada(self):
        operacion = self.operar()
        services.anular_operacion_en_efectivo(self.caja, operacion.pk)
        admin = Client()
        admin.force_login(_login_con_rol('admin_historial_anul', 'administrador'))
        resp = admin.get('/api/transacciones/gestion/historial/', {'estado': 'ANULADA'})
        self.assertContains(resp, 'Anulada')
        self.assertContains(resp, 'Operación anulada por el cajero')
        sin = admin.get('/api/transacciones/gestion/historial/', {'estado': 'EXITOSA'})
        self.assertNotContains(sin, 'Operación anulada por el cajero')
