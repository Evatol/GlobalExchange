from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.divisas.models import Moneda

from . import services
from .models import (
    AsignacionCajero, Billete, Caja, MovimientoBillete, StockBillete, Sucursal,Arqueo,
)
from .test_sucursales import _cajero, _login_con_rol, _usuario_negocio

User = get_user_model()


class BaseBilletesTests(APITestCase):
    """Dos cajeros en una sucursal, cada uno con su caja abierta y su propio
    stock: caja1 con 5 x 100 y 10 x 50 (total 1000); caja2 con 2 x 100."""

    def setUp(self):
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.b100 = Billete.objects.create(moneda=self.usd, denominacion=Decimal('100'))
        self.b50 = Billete.objects.create(moneda=self.usd, denominacion=Decimal('50'))
        self.sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')

        self.cajero1 = _cajero('caj1')
        self.cajero2 = _cajero('caj2')
        self.login1 = User.objects.get(username='caj1')
        self.login2 = User.objects.get(username='caj2')
        for cajero in (self.cajero1, self.cajero2):
            AsignacionCajero.objects.create(sucursal=self.sucursal, usuario=cajero)

        self.caja1 = Caja.objects.create(
            sucursal=self.sucursal, cajero=self.cajero1, saldo_inicial=0, saldo_actual=0
        )
        self.caja2 = Caja.objects.create(
            sucursal=self.sucursal, cajero=self.cajero2, saldo_inicial=0, saldo_actual=0
        )
        services.abrir_caja(self.caja1, self.cajero1, {self.b100.id: 5, self.b50.id: 10})
        services.abrir_caja(self.caja2, self.cajero2, {self.b100.id: 2})
        self.caja1.refresh_from_db()
        self.caja2.refresh_from_db()

    def stock(self, caja, billete):
        fila = StockBillete.objects.filter(caja=caja, billete=billete).first()
        return fila.cantidad if fila else 0


class ServiciosBilletesTests(BaseBilletesTests):
    def test_el_stock_es_por_caja_y_no_global(self):
        self.assertEqual(self.stock(self.caja1, self.b100), 5)
        self.assertEqual(self.stock(self.caja2, self.b100), 2)
        self.assertEqual(self.stock(self.caja2, self.b50), 0)

    def test_registra_recibidos_y_entregados_por_denominacion(self):
        services.registrar_movimientos_billetes(
            self.caja1, self.cajero1, None, {self.b50.id: 4}, {self.b100.id: 2}
        )
        self.assertEqual(self.stock(self.caja1, self.b100), 3)
        self.assertEqual(self.stock(self.caja1, self.b50), 14)
        salida = MovimientoBillete.objects.get(caja=self.caja1, tipo='SALIDA')
        self.assertEqual(salida.billete, self.b100)
        self.assertEqual(salida.cantidad, 2)
        self.assertEqual(salida.usuario, self.cajero1)
        self.assertEqual(self.stock(self.caja2, self.b100), 2)  # la otra caja no se toca

    def test_no_se_puede_entregar_mas_de_lo_que_hay(self):
        with self.assertRaises(ValidationError):
            services.registrar_movimientos_billetes(
                self.caja1, self.cajero1, None, None, {self.b100.id: 99}
            )
        self.assertEqual(self.stock(self.caja1, self.b100), 5)

    def test_inventario_con_subtotales_y_total_por_moneda(self):
        inventario = services.inventario_por_moneda(self.caja1)
        usd = next(g for g in inventario if g['moneda'] == 'USD')
        self.assertEqual(usd['total'], Decimal('1000'))
        subtotales = {d['denominacion']: d['subtotal'] for d in usd['denominaciones']}
        self.assertEqual(subtotales[Decimal('100')], Decimal('500'))
        self.assertEqual(subtotales[Decimal('50')], Decimal('500'))

    def test_arqueo_registra_la_diferencia_sin_tocar_el_stock(self):
        arqueo = services.registrar_arqueo(
            self.caja1, self.cajero1, self.usd, {self.b100.id: 4, self.b50.id: 10}
        )
        self.assertEqual(arqueo.total_esperado, Decimal('1000'))
        self.assertEqual(arqueo.total_contado, Decimal('900'))
        self.assertEqual(arqueo.diferencia, Decimal('-100'))
        self.assertEqual(arqueo.detalles.get(billete=self.b100).diferencia, -1)
        self.assertEqual(self.stock(self.caja1, self.b100), 5)  # el arqueo no ajusta

    def test_arqueo_sin_diferencia(self):
        arqueo = services.registrar_arqueo(
            self.caja1, self.cajero1, self.usd, {self.b100.id: 5, self.b50.id: 10}
        )
        self.assertEqual(arqueo.diferencia, Decimal('0'))


class ApiBilletesTests(BaseBilletesTests):
    def test_administrador_carga_denominaciones(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))
        r = self.client.post(
            reverse('billete-list'),
            {'moneda': self.usd.id, 'denominacion': '20'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data['estado'])

    def test_denominacion_repetida_rechazada(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))
        r = self.client.post(
            reverse('billete-list'),
            {'moneda': self.usd.id, 'denominacion': '100'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cajero_no_administra_denominaciones(self):
        self.client.force_login(self.login1)
        r = self.client.post(
            reverse('billete-list'),
            {'moneda': self.usd.id, 'denominacion': '20'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cajero_ve_solo_el_inventario_de_su_caja(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('mi_inventario'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(str(r.data['monedas'][0]['total'])), Decimal('1000'))

        self.client.force_login(self.login2)
        r = self.client.get(reverse('mi_inventario'))
        self.assertEqual(Decimal(str(r.data['monedas'][0]['total'])), Decimal('200'))

    def test_arqueo_del_cajero_por_api(self):
        self.client.force_login(self.login1)
        r = self.client.post(
            reverse('arqueo-list'),
            {'moneda': self.usd.id,
             'contados': {str(self.b100.id): 4, str(self.b50.id): 10}},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(str(r.data['diferencia'])), Decimal('-100'))
        self.assertEqual(self.stock(self.caja1, self.b100), 5)

    def test_administrador_no_hace_arqueos(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))
        r = self.client.post(
            reverse('arqueo-list'), {'moneda': self.usd.id, 'contados': {}}, format='json'
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cajero_sin_caja_abierta_recibe_error_claro(self):
        self.caja1.cerrar()
        self.client.force_login(self.login1)
        r = self.client.get(reverse('mi_inventario'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('caja abierta', str(r.data))

    def test_administrador_crea_caja_y_la_abre_con_carga_inicial(self):
        admin = _login_con_rol('admin1', 'administrador')
        _usuario_negocio('admin1')  # quien abre la caja queda en los movimientos
        self.client.force_login(admin)
        nueva = Sucursal.objects.create(nombre='Norte', direccion='Luque')
        cajero3 = _cajero('caj3')
        AsignacionCajero.objects.create(sucursal=nueva, usuario=cajero3)

        r = self.client.post(
            reverse('caja-list'), {'sucursal': nueva.id, 'cajero': cajero3.id}, format='json'
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

        r = self.client.post(
            reverse('caja-abrir', args=[r.data['id']]),
            {'carga_inicial': {str(self.b100.id): 3}},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['estado'], 'ABIERTA')
        self.assertEqual(self.stock(Caja.objects.get(cajero=cajero3), self.b100), 3)

class PantallasBilletesTests(BaseBilletesTests):
    def _admin(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))

    def _caja_cerrada(self):
        sucursal = Sucursal.objects.create(nombre='Norte', direccion='Luque')
        cajero = _cajero('caj3')
        AsignacionCajero.objects.create(sucursal=sucursal, usuario=cajero)
        return Caja.objects.create(
            sucursal=sucursal, cajero=cajero, saldo_inicial=0, saldo_actual=0
        )

    # ---- administrador ----------------------------------------------------

    def test_admin_ve_denominaciones(self):
        self._admin()
        r = self.client.get(reverse('gestion_denominaciones'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.context['billetes']), 2)

    def test_cajero_no_accede_a_las_pantallas_del_administrador(self):
        self.client.force_login(self.login1)
        for nombre in ('gestion_denominaciones', 'gestion_cajas'):
            r = self.client.get(reverse(nombre))
            self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_crear_denominacion_desde_la_pantalla(self):
        self._admin()
        r = self.client.post(
            reverse('gestion_denominaciones'),
            {'moneda': self.usd.id, 'denominacion': '20'},
        )
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        self.assertTrue(Billete.objects.get(moneda=self.usd, denominacion=20).estado)

    def test_denominacion_repetida_muestra_el_error(self):
        self._admin()
        r = self.client.post(
            reverse('gestion_denominaciones'),
            {'moneda': self.usd.id, 'denominacion': '100'},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertContains(r, 'ya existe')

    def test_desactivar_denominacion_solo_por_post(self):
        self._admin()
        url = reverse('billete_toggle', args=[self.b50.id])
        self.assertEqual(self.client.get(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        r = self.client.post(url)
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        self.b50.refresh_from_db()
        self.assertFalse(self.b50.estado)

    def test_admin_crea_caja_y_la_abre_desde_las_pantallas(self):
        self._admin()
        nueva = Sucursal.objects.create(nombre='Norte', direccion='Luque')
        cajero3 = _cajero('caj3')
        asignacion = AsignacionCajero.objects.create(sucursal=nueva, usuario=cajero3)

        r = self.client.post(reverse('gestion_cajas'), {'asignacion': asignacion.id})
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        caja = Caja.objects.get(cajero=cajero3)
        self.assertEqual(caja.estado, 'CERRADA')

        r = self.client.post(
            reverse('caja_abrir', args=[caja.id]),
            {f'carga_{self.b100.id}': '3', f'carga_{self.b50.id}': '0'},
        )
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        caja.refresh_from_db()
        self.assertEqual(caja.estado, 'ABIERTA')
        self.assertEqual(self.stock(caja, self.b100), 3)

    def test_abrir_caja_sin_cargar_billetes(self):
        self._admin()
        caja = self._caja_cerrada()
        r = self.client.post(
            reverse('caja_abrir', args=[caja.id]),
            {f'carga_{self.b100.id}': '0', f'carga_{self.b50.id}': ''},
        )
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        caja.refresh_from_db()
        self.assertEqual(caja.estado, 'ABIERTA')

    def test_abrir_caja_con_texto_no_numerico_muestra_error(self):
        self._admin()
        caja = self._caja_cerrada()
        r = self.client.post(
            reverse('caja_abrir', args=[caja.id]), {f'carga_{self.b100.id}': 'abc'}
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertContains(r, 'números enteros')
        caja.refresh_from_db()
        self.assertEqual(caja.estado, 'CERRADA')

    # ---- cajero -----------------------------------------------------------

    def test_cajero_ve_su_inventario_con_el_total(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('mi_caja'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.context['monedas'][0]['total'], Decimal('1000'))

        self.client.force_login(self.login2)
        r = self.client.get(reverse('mi_caja'))
        self.assertEqual(r.context['monedas'][0]['total'], Decimal('200'))

    def test_cajero_registra_el_arqueo_desde_la_pantalla(self):
        self.client.force_login(self.login1)
        r = self.client.post(reverse('mi_caja'), {
            'moneda': self.usd.id,
            f'contado_{self.b100.id}': '4',
            f'contado_{self.b50.id}': '10',
        })
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        arqueo = Arqueo.objects.get(cajero=self.cajero1)
        self.assertEqual(arqueo.diferencia, Decimal('-100'))
        self.assertEqual(self.stock(self.caja1, self.b100), 5)  # el arqueo no ajusta

    def test_arqueo_con_valores_no_numericos_se_rechaza(self):
        self.client.force_login(self.login1)
        r = self.client.post(reverse('mi_caja'), {
            'moneda': self.usd.id, f'contado_{self.b100.id}': 'abc',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertContains(r, 'números enteros')
        self.assertEqual(Arqueo.objects.count(), 0)

    def test_cajero_sin_caja_abierta_ve_un_aviso_y_no_un_error(self):
        self.caja1.cerrar()
        self.client.force_login(self.login1)
        r = self.client.get(reverse('mi_caja'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIsNone(r.context['caja'])

    def test_administrador_no_entra_a_mi_caja(self):
        self._admin()
        r = self.client.get(reverse('mi_caja'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cajero_ve_su_menu_y_no_el_general(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('menu_principal'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(r, 'usuarios/menu_cajero.html')