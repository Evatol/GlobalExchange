"""Pruebas de la consulta y descarga de facturas (Sprint 5)."""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.divisas.models import Moneda
from apps.transacciones.models import MetodoPago, Transaccion
from apps.usuarios.models import Cliente, Usuario

from .models import Factura

User = get_user_model()


def _login_con_rol(username, rol):
    """Usuario de login con el grupo ``rol``, como lo deja la sincronización
    de roles desde Keycloak."""
    user = User.objects.create_user(username, password='x')
    grupo, _ = Group.objects.get_or_create(name=rol)
    user.groups.add(grupo)
    return user


def _usuario_final(username, cliente):
    """Usuario final: login con el rol, perfil de negocio y un cliente asociado."""
    login = _login_con_rol(username, 'usuario_final')
    perfil = Usuario.objects.create(
        username=username, email=f'{username}@test.com', nombres='Test',
        apellidos='Test', telefono='0981000000', direccion='Asunción',
    )
    perfil.clientes.add(cliente)
    return login, perfil


class BaseFacturasTests(TestCase):
    """Dos clientes, cada uno con un usuario final y una factura emitida."""

    def setUp(self):
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.eur = Moneda.objects.create(codigo='EUR', nombre='Euro', simbolo='€')
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        self.cliente1 = Cliente.objects.create(nombre='Ana', documento='111', tipo='FISICA')
        self.cliente2 = Cliente.objects.create(nombre='Beto', documento='222', tipo='FISICA')
        self.login1, self.perfil1 = _usuario_final('ana', self.cliente1)
        self.login2, self.perfil2 = _usuario_final('beto', self.cliente2)
        self.f1 = self._factura(self.perfil1, self.cliente1, self.usd)
        self.f2 = self._factura(self.perfil2, self.cliente2, self.eur)

    def _factura(self, perfil, cliente, moneda, estado='EMITIDA'):
        transaccion = Transaccion.objects.create(
            usuario=perfil, cliente=cliente, moneda=moneda, metodo_pago=self.metodo,
            tipo='COMPRA', cantidad=Decimal('100'), tasa_cambio=Decimal('7500'),
        )
        transaccion.calcular_tasas_y_comisiones()
        transaccion.estado = 'EXITOSA'
        transaccion.save()
        factura = Factura(transaccion=transaccion)
        factura.generar()
        if estado != 'EMITIDA':
            factura.estado = estado
            factura.save()
        return factura


class ListadoFacturasTests(BaseFacturasTests):
    def ids(self, respuesta):
        return {f.id for f in respuesta.context['facturas']}

    def test_el_usuario_final_ve_solo_las_facturas_de_su_cliente(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('lista_facturas'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ids(r), {self.f1.id})

    def test_analista_y_administrador_ven_todas(self):
        for rol in ('analista', 'administrador'):
            self.client.force_login(_login_con_rol(f'user_{rol}', rol))
            r = self.client.get(reverse('lista_facturas'))
            self.assertEqual(self.ids(r), {self.f1.id, self.f2.id})

    def test_filtra_por_numero(self):
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        r = self.client.get(reverse('lista_facturas'), {'numero': self.f2.numero})
        self.assertEqual(self.ids(r), {self.f2.id})

    def test_filtra_por_moneda(self):
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        r = self.client.get(reverse('lista_facturas'), {'moneda': self.usd.id})
        self.assertEqual(self.ids(r), {self.f1.id})

    def test_filtra_por_estado(self):
        anulada = self._factura(self.perfil1, self.cliente1, self.usd, estado='ANULADA')
        self.client.force_login(self.login1)
        r = self.client.get(reverse('lista_facturas'), {'estado': 'anulada'})
        self.assertEqual(self.ids(r), {anulada.id})

    def test_filtra_por_fecha(self):
        Factura.objects.filter(pk=self.f1.pk).update(fecha=datetime.date(2026, 1, 15))
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        r = self.client.get(
            reverse('lista_facturas'),
            {'fecha_desde': '2026-01-01', 'fecha_hasta': '2026-01-31'},
        )
        self.assertEqual(self.ids(r), {self.f1.id})

    def test_un_filtro_invalido_no_rompe_la_pantalla(self):
        self.client.force_login(self.login1)
        r = self.client.get(
            reverse('lista_facturas'),
            {'fecha_desde': '2026-13-45', 'numero': 'abc', 'moneda': 'x'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['errores']), 3)
        self.assertEqual(self.ids(r), {self.f1.id})

    def test_requiere_iniciar_sesion(self):
        r = self.client.get(reverse('lista_facturas'))
        self.assertEqual(r.status_code, 302)

    def test_es_solo_lectura(self):
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        r = self.client.post(reverse('lista_facturas'), {})
        self.assertEqual(r.status_code, 405)


class DetalleFacturaTests(BaseFacturasTests):
    def test_detalle_con_montos_tasa_comision_y_transaccion(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('detalle_factura', args=[self.f1.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['transaccion'], self.f1.transaccion)
        self.assertEqual(r.context['transaccion'].tasa_cambio, Decimal('7500'))
        self.assertEqual(r.context['transaccion'].monto_comision, Decimal('11250.00'))
        self.assertContains(r, self.f1.numero)
        self.assertContains(r, f'#{self.f1.transaccion.id}')

    def test_factura_de_otro_cliente_se_deniega_con_mensaje(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('detalle_factura', args=[self.f2.id]))
        self.assertContains(r, 'pertenece a otro cliente', status_code=403)

    def test_factura_no_emitida_se_deniega_con_mensaje(self):
        pendiente = self._factura(self.perfil1, self.cliente1, self.usd, estado='PENDIENTE')
        self.client.force_login(self.login1)
        r = self.client.get(reverse('detalle_factura', args=[pendiente.id]))
        self.assertContains(r, 'no fue emitida', status_code=403)

    def test_el_analista_consulta_la_factura_de_cualquier_cliente(self):
        anulada = self._factura(self.perfil2, self.cliente2, self.eur, estado='ANULADA')
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        for factura in (self.f1, self.f2, anulada):
            r = self.client.get(reverse('detalle_factura', args=[factura.id]))
            self.assertEqual(r.status_code, 200)

    def test_factura_inexistente_da_404(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('detalle_factura', args=[99999]))
        self.assertEqual(r.status_code, 404)


class DescargaFacturaTests(BaseFacturasTests):
    def test_descarga_el_pdf_de_una_factura_emitida(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('descargar_factura_pdf', args=[self.f1.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn(self.f1.numero, r['Content-Disposition'])
        self.assertTrue(r.content.startswith(b'%PDF'))

    def test_pdf_de_factura_ajena_se_deniega(self):
        self.client.force_login(self.login1)
        r = self.client.get(reverse('descargar_factura_pdf', args=[self.f2.id]))
        self.assertContains(r, 'pertenece a otro cliente', status_code=403)

    def test_pdf_de_factura_no_emitida_se_deniega(self):
        pendiente = self._factura(self.perfil1, self.cliente1, self.usd, estado='PENDIENTE')
        self.client.force_login(self.login1)
        r = self.client.get(reverse('descargar_factura_pdf', args=[pendiente.id]))
        self.assertContains(r, 'no fue emitida', status_code=403)

    def test_el_analista_descarga_emitidas_pero_no_las_no_emitidas(self):
        pendiente = self._factura(self.perfil2, self.cliente2, self.eur, estado='PENDIENTE')
        self.client.force_login(_login_con_rol('analista1', 'analista'))
        r = self.client.get(reverse('descargar_factura_pdf', args=[self.f2.id]))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('descargar_factura_pdf', args=[pendiente.id]))
        self.assertContains(r, 'Solo se pueden descargar facturas emitidas', status_code=403)

    def test_pdf_de_un_cambio_entre_divisas(self):
        cambio = Transaccion.objects.create(
            usuario=self.perfil1, cliente=self.cliente1, moneda=self.usd,
            metodo_pago=self.metodo, tipo='CAMBIO', cantidad=Decimal('100'),
            tasa_cambio=Decimal('7500'), moneda_destino=self.eur,
            tasa_cambio_destino=Decimal('8100'),
        )
        cambio.calcular_tasas_y_comisiones()
        cambio.estado = 'EXITOSA'
        cambio.save()
        factura = Factura(transaccion=cambio)
        factura.generar()
        self.client.force_login(self.login1)
        r = self.client.get(reverse('descargar_factura_pdf', args=[factura.id]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))