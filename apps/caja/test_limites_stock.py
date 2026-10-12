"""Tests de RF107: alerta cuando el stock de billetes de una moneda llega al límite
mínimo o máximo configurado."""
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status

from apps.divisas.models import Moneda
from apps.notificaciones.models import Notificaciones
from apps.usuarios.models import Cliente, Usuario

from . import services
from .models import AsignacionCajero, Caja, LimiteStock
from .test_cierre_movimientos import BaseCajaPresencialTests
from .test_sucursales import _cajero, _login_con_rol, _usuario_negocio

User = get_user_model()


class LimiteStockModeloTests(TestCase):
    def setUp(self):
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')

    def _limite(self, minimo=None, maximo=None):
        return LimiteStock(moneda=self.usd, minimo=minimo, maximo=maximo)

    def test_limites_validos(self):
        for minimo, maximo in ((None, None), (Decimal('100'), None), (None, Decimal('500')),
                               (Decimal('0'), Decimal('500')), (Decimal('500'), Decimal('500'))):
            with self.subTest(minimo=minimo, maximo=maximo):
                self._limite(minimo, maximo).clean()  # no debe levantar

    def test_reglas_de_validacion(self):
        casos = {
            'minimo': [(Decimal('-1'), None), (Decimal('600'), Decimal('500'))],
            'maximo': [(None, Decimal('0')), (None, Decimal('-5'))],
        }
        for campo, valores in casos.items():
            for minimo, maximo in valores:
                with self.subTest(minimo=minimo, maximo=maximo), self.assertRaises(ValidationError) as ctx:
                    self._limite(minimo, maximo).clean()
                self.assertIn(campo, ctx.exception.message_dict)

    def test_el_nivel_en_los_bordes(self):
        """Llegar al límite ya cuenta: ``<= mínimo`` es BAJO y ``>= máximo`` es ALTO."""
        limite = self._limite(Decimal('100'), Decimal('500'))
        self.assertEqual(limite.nivel(Decimal('99.99')), 'BAJO')
        self.assertEqual(limite.nivel(Decimal('100')), 'BAJO')
        self.assertIsNone(limite.nivel(Decimal('100.01')))
        self.assertIsNone(limite.nivel(Decimal('499.99')))
        self.assertEqual(limite.nivel(Decimal('500')), 'ALTO')
        self.assertEqual(limite.nivel(Decimal('9999')), 'ALTO')

    def test_sin_limite_de_un_lado_ese_lado_no_alerta(self):
        self.assertIsNone(self._limite(None, Decimal('500')).nivel(Decimal('0')))
        self.assertIsNone(self._limite(Decimal('100'), None).nivel(Decimal('99999')))
        self.assertIsNone(self._limite().nivel(Decimal('0')))

    def test_un_limite_por_moneda(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1'))
        with self.assertRaises(IntegrityError):
            LimiteStock.objects.create(moneda=self.usd, maximo=Decimal('5'))


class AlertasDeStockTests(BaseCajaPresencialTests):
    """La caja de la base tiene 1.860 USD, 1.850 EUR y 1.870.000 PYG."""

    def test_sin_limites_configurados_no_hay_alertas(self):
        self.assertEqual(services.alertas_de_stock(self.caja), [])

    def test_dentro_de_los_limites_no_hay_alerta(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1000'), maximo=Decimal('5000'))
        self.assertEqual(services.alertas_de_stock(self.caja), [])

    def test_llegar_al_minimo_es_alerta_baja_con_un_mensaje_claro(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1860'))
        (alerta,) = services.alertas_de_stock(self.caja)
        self.assertEqual((alerta['moneda'], alerta['nivel']), ('USD', 'BAJO'))
        self.assertEqual(alerta['saldo'], Decimal('1860'))
        self.assertEqual(alerta['mensaje'], 'hay 1.860 USD en billetes y el mínimo configurado es 1.860.')

    def test_llegar_al_maximo_es_alerta_alta(self):
        LimiteStock.objects.create(moneda=self.usd, maximo=Decimal('1860'))
        (alerta,) = services.alertas_de_stock(self.caja)
        self.assertEqual(alerta['nivel'], 'ALTO')
        self.assertIn('el máximo configurado es 1.860', alerta['mensaje'])

    def test_solo_aparecen_las_monedas_con_alerta(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('5000'))      # alerta
        LimiteStock.objects.create(moneda=self.eur, minimo=Decimal('10'))        # bien
        self.assertEqual([a['moneda'] for a in services.alertas_de_stock(self.caja)], ['USD'])
        self.assertEqual(services.alertas_de_stock(self.caja, [self.eur.id]), [])  # acotado

    def test_una_moneda_sin_billetes_en_la_caja_vale_cero(self):
        brl = Moneda.objects.create(codigo='BRL', nombre='Real', simbolo='R$')
        LimiteStock.objects.create(moneda=brl, minimo=Decimal('10'))
        (alerta,) = services.alertas_de_stock(self.caja)
        self.assertEqual((alerta['moneda'], alerta['saldo']), ('BRL', Decimal('0')))

    def test_el_balance_incluye_las_alertas(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('5000'))
        self.assertEqual([a['moneda'] for a in services.balance_caja(self.caja)['alertas']], ['USD'])

    def test_los_numeros_se_formatean_sin_ceros_de_mas(self):
        self.assertEqual(services._formato(Decimal('1847.00')), '1.847')
        self.assertEqual(services._formato(Decimal('0.50')), '0,50')
        self.assertEqual(services._formato(Decimal('1870000')), '1.870.000')


class AvisosDeStockTests(BaseCajaPresencialTests):
    """El aviso llega a los administradores y al cajero, y solo cuando el stock
    cruza el límite (no en cada operación)."""

    def setUp(self):
        super().setUp()
        self.admin_u = _usuario_negocio('admin_ls')
        _login_con_rol('admin_ls', 'administrador')
        self.root_u = _usuario_negocio('root_ls')
        User.objects.create_user('root_ls', is_superuser=True)
        # un administrador que todavía no tiene su Usuario de negocio (no entró nunca)
        _login_con_rol('admin_sin_perfil', 'administrador')
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1850'))   # stock: 1.860

    def _avisos(self):
        return Notificaciones.objects.filter(tipo='stock_billetes')

    def _comprar_usd(self, cantidad):
        return self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal(cantidad))

    def _vender_usd(self, cantidad):
        return self.operar(tipo='VENTA', moneda_codigo='USD', cantidad=Decimal(cantidad))

    def test_al_bajar_del_minimo_avisa_a_los_administradores_y_al_cajero(self):
        self._comprar_usd('13')  # la caja entrega 13 USD: 1.860 -> 1.847
        destinatarios = set(self._avisos().values_list('usuario__username', flat=True))
        self.assertEqual(destinatarios, {'admin_ls', 'root_ls', 'caj_pres'})  # superusuario incluido
        self.assertEqual(self._avisos().count(), 3)
        aviso = self._avisos().get(usuario=self.cajero)
        self.assertEqual(aviso.titulo, 'Stock de billetes bajo: USD')
        self.assertIn(f'Caja #{self.caja.pk} (Central, cajero caj_pres)', aviso.mensaje)
        self.assertIn('hay 1.847 USD en billetes y el mínimo configurado es 1.850', aviso.mensaje)
        self.assertFalse(aviso.leida)

    def test_si_sigue_bajo_no_se_repite_el_aviso(self):
        self._comprar_usd('13')
        avisos = self._avisos().count()
        self._comprar_usd('5')   # 1.847 -> 1.842: sigue bajo
        self.assertEqual(self._avisos().count(), avisos)

    def test_si_vuelve_a_la_normalidad_y_cruza_de_nuevo_avisa_otra_vez(self):
        self._comprar_usd('13')                      # BAJO: avisa
        base = self._avisos().count()
        self._vender_usd('100')                      # la caja recibe 100 USD -> 1.947: normal, sin aviso
        self.assertEqual(self._avisos().count(), base)
        self.assertEqual(services.alertas_de_stock(self.caja), [])
        self._comprar_usd('100')                     # 1.947 -> 1.847: cruza otra vez
        self.assertEqual(self._avisos().count(), base * 2)

    def test_si_ya_estaba_bajo_antes_de_operar_no_hay_aviso_nuevo(self):
        LimiteStock.objects.filter(moneda=self.usd).update(minimo=Decimal('5000'))  # ya es BAJO
        self._comprar_usd('13')
        self.assertEqual(self._avisos().count(), 0)

    def test_el_maximo_avisa_como_stock_alto(self):
        LimiteStock.objects.filter(moneda=self.usd).update(minimo=None, maximo=Decimal('1900'))
        self._vender_usd('100')                      # la caja recibe 100 USD -> 1.960 >= 1.900
        aviso = self._avisos().get(usuario=self.cajero)
        self.assertEqual(aviso.titulo, 'Stock de billetes alto: USD')
        self.assertIn('el máximo configurado es 1.900', aviso.mensaje)

    def test_solo_avisa_de_las_monedas_con_limite(self):
        self._comprar_usd('13')  # mueve PYG y USD, pero solo USD tiene límite
        self.assertEqual(set(self._avisos().values_list('titulo', flat=True)), {'Stock de billetes bajo: USD'})

    def test_sin_limites_configurados_no_avisa(self):
        LimiteStock.objects.all().delete()
        self._comprar_usd('13')
        self.assertEqual(self._avisos().count(), 0)

    def test_una_operacion_que_falla_no_deja_avisos(self):
        with self.assertRaises(ValidationError):
            self._comprar_usd('5000')  # no hay tantos dólares: se revierte todo
        self.assertEqual(self._avisos().count(), 0)

    def test_la_carga_inicial_de_la_apertura_tambien_puede_avisar(self):
        LimiteStock.objects.filter(moneda=self.usd).update(minimo=None, maximo=Decimal('100'))
        otro = _cajero('otro_caj_ls')
        AsignacionCajero.objects.create(sucursal=self.sucursal, usuario=otro)
        caja2 = Caja.objects.create(sucursal=self.sucursal, cajero=otro, saldo_inicial=0, saldo_actual=0)
        services.abrir_caja(caja2, otro, {self.b[('USD', 100)].id: 2})   # 200 USD >= 100
        aviso = self._avisos().get(usuario=otro)
        self.assertEqual(aviso.titulo, 'Stock de billetes alto: USD')
        self.assertIn(f'Caja #{caja2.pk}', aviso.mensaje)


class VisibilidadDeLasAlertasTests(BaseCajaPresencialTests):
    def setUp(self):
        super().setUp()
        self.admin = _login_con_rol('admin_vis', 'administrador')
        _usuario_negocio('admin_vis')
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1850'))
        self.client.force_login(self.login)

    def _bajar_el_stock(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('13'))

    def test_mi_caja_muestra_la_alerta_mientras_dure(self):
        self.assertNotContains(self.client.get(reverse('mi_caja')), 'Stock bajo de USD')
        self._bajar_el_stock()
        resp = self.client.get(reverse('mi_caja'))
        self.assertContains(resp, 'Stock bajo de USD')
        self.assertContains(resp, 'el mínimo configurado es 1.850')
        # no desaparece al recargar: es el estado actual, no un aviso que se gasta
        self.assertContains(self.client.get(reverse('mi_caja')), 'Stock bajo de USD')

    def test_la_alerta_desaparece_cuando_el_stock_se_recupera(self):
        self._bajar_el_stock()
        self.operar(tipo='VENTA', moneda_codigo='USD', cantidad=Decimal('100'))
        self.assertNotContains(self.client.get(reverse('mi_caja')), 'Stock bajo de USD')

    def test_atender_cliente_tambien_muestra_la_alerta(self):
        self._bajar_el_stock()
        self.assertContains(self.client.get(reverse('mostrador')), 'Stock bajo de USD')

    def test_el_administrador_la_ve_en_el_balance_de_la_caja(self):
        self._bajar_el_stock()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('caja_balance', args=[self.caja.pk])), 'Stock bajo de USD')

    def test_la_api_de_balance_incluye_las_alertas(self):
        self._bajar_el_stock()
        resp = self.client.get(reverse('mi_balance'))
        self.assertEqual([(a['moneda'], a['nivel']) for a in resp.data['alertas']], [('USD', 'BAJO')])

    def test_el_cajero_recibe_el_aviso_en_pantalla_y_lo_puede_cerrar(self):
        """El middleware del cajero solo dejaba /api/caja/: ahora también sus avisos."""
        self._bajar_el_stock()
        resp = self.client.get(reverse('api_notificaciones_nuevas'))
        self.assertEqual(resp.status_code, 200)
        (aviso,) = resp.json()['notificaciones']
        self.assertEqual(aviso['titulo'], 'Stock de billetes bajo: USD')
        resp = self.client.post(reverse('api_notificacion_leida', args=[aviso['id']]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(reverse('api_notificaciones_nuevas')).json()['notificaciones'], [])

    def test_el_cajero_sigue_sin_acceso_al_resto_del_sistema(self):
        self.assertEqual(self.client.get('/api/transacciones/gestion/operar/').status_code, 403)
        self.assertEqual(self.client.get('/api/divisas/gestion/monedas/').status_code, 403)

    def test_las_pantallas_del_cajero_consultan_los_avisos(self):
        for url in (reverse('menu_principal'), reverse('mi_caja'), reverse('mostrador')):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'id="contenedor-alertas-divisas"')


class ConfigurarLosLimitesTests(BaseCajaPresencialTests):
    def setUp(self):
        super().setUp()
        self.admin = _login_con_rol('admin_cfg', 'administrador')
        _usuario_negocio('admin_cfg')
        self.url = reverse('gestion_limites_stock')
        self.client.force_login(self.admin)

    # --- pantalla
    def test_la_pantalla_lista_las_monedas_activas(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        for codigo in ('PYG', 'USD', 'EUR'):
            self.assertContains(resp, f'<strong>{codigo}</strong>', html=True)
        self.assertContains(resp, 'sin límite')

    def test_guardar_crea_actualiza_y_borra_limites(self):
        datos = {f'minimo_{self.usd.id}': '1850', f'maximo_{self.usd.id}': '3000',
                 f'minimo_{self.eur.id}': '', f'maximo_{self.eur.id}': '20000',
                 f'minimo_{self.pyg.id}': '', f'maximo_{self.pyg.id}': ''}
        resp = self.client.post(self.url, datos, follow=True)
        self.assertContains(resp, 'Límites de stock guardados')
        usd = LimiteStock.objects.get(moneda=self.usd)
        self.assertEqual((usd.minimo, usd.maximo), (Decimal('1850'), Decimal('3000')))
        eur = LimiteStock.objects.get(moneda=self.eur)
        self.assertEqual((eur.minimo, eur.maximo), (None, Decimal('20000')))
        self.assertFalse(LimiteStock.objects.filter(moneda=self.pyg).exists())
        # vaciar los dos campos borra el límite
        datos.update({f'minimo_{self.usd.id}': '', f'maximo_{self.usd.id}': ''})
        self.client.post(self.url, datos)
        self.assertFalse(LimiteStock.objects.filter(moneda=self.usd).exists())

    def test_acepta_coma_decimal(self):
        self.client.post(self.url, {f'minimo_{self.eur.id}': '100,5'})
        self.assertEqual(LimiteStock.objects.get(moneda=self.eur).minimo, Decimal('100.5'))

    def test_si_una_fila_tiene_error_no_se_guarda_ninguna(self):
        LimiteStock.objects.create(moneda=self.eur, minimo=Decimal('7'))
        resp = self.client.post(self.url, {
            f'minimo_{self.usd.id}': '100', f'maximo_{self.usd.id}': '50',     # mínimo > máximo
            f'minimo_{self.eur.id}': 'abc',                                    # no es un número
            f'minimo_{self.pyg.id}': '10',                                     # esta sí es válida
        })
        self.assertContains(resp, 'USD: El mínimo no puede ser mayor que el máximo')
        self.assertContains(resp, 'EUR: &quot;abc&quot; no es un número', html=False)
        self.assertEqual(LimiteStock.objects.get(moneda=self.eur).minimo, Decimal('7'))  # intacto
        self.assertFalse(LimiteStock.objects.filter(moneda__in=[self.usd, self.pyg]).exists())
        self.assertContains(resp, 'value="abc"')   # se vuelve a mostrar lo que se escribió

    def test_valores_no_finitos_se_rechazan(self):
        resp = self.client.post(self.url, {f'maximo_{self.usd.id}': 'NaN'})
        self.assertContains(resp, 'no es un número')
        self.assertFalse(LimiteStock.objects.exists())

    def test_solo_el_administrador(self):
        for usuario in (self.login, _login_con_rol('analista_cfg', 'analista'), _login_con_rol('final_cfg', 'usuario_final')):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url).status_code, 403, usuario.username)
            self.assertEqual(self.client.post(self.url, {f'maximo_{self.usd.id}': '5'}).status_code, 403)
        self.assertFalse(LimiteStock.objects.exists())

    def test_el_menu_del_administrador_lo_ofrece(self):
        """El login real marca como staff y superusuario a quien tiene el rol
        administrador (``CustomOIDCBackend``), y el menú muestra la administración
        solo a ellos."""
        self.client.force_login(User.objects.create_user('root_menu', is_staff=True, is_superuser=True))
        resp = self.client.get(reverse('menu_principal'))
        self.assertContains(resp, 'Límites de Stock')
        self.assertContains(resp, f'href="{self.url}"')

    # --- API
    def test_api_crear_listar_editar_y_borrar(self):
        r = self.client.post(reverse('limitestock-list'), {'moneda': self.usd.id, 'minimo': '1850', 'maximo': '3000'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        self.assertEqual(r.data['moneda_codigo'], 'USD')
        pk = r.data['id']
        self.assertEqual(self.client.get(reverse('limitestock-list')).data['count'], 1)
        r = self.client.patch(reverse('limitestock-detail', args=[pk]), {'maximo': None}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(LimiteStock.objects.get(pk=pk).maximo)
        self.assertEqual(self.client.delete(reverse('limitestock-detail', args=[pk])).status_code, 204)

    def test_api_valida_las_reglas(self):
        for datos in ({'minimo': '600', 'maximo': '500'}, {'minimo': '-1'}, {'maximo': '0'}):
            with self.subTest(datos=datos):
                r = self.client.post(reverse('limitestock-list'), dict(moneda=self.usd.id, **datos), format='json')
                self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_api_un_solo_limite_por_moneda(self):
        LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('1'))
        r = self.client.post(reverse('limitestock-list'), {'moneda': self.usd.id, 'minimo': '2'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_api_editar_valida_contra_lo_que_ya_tenia(self):
        limite = LimiteStock.objects.create(moneda=self.usd, minimo=Decimal('100'), maximo=Decimal('500'))
        r = self.client.patch(reverse('limitestock-detail', args=[limite.pk]), {'minimo': '900'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)  # 900 > 500, que ya estaba

    def test_api_solo_el_administrador(self):
        for usuario in (self.login, _login_con_rol('analista_cfg2', 'analista')):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(reverse('limitestock-list')).status_code, 403)
            self.assertEqual(self.client.post(reverse('limitestock-list'), {'moneda': self.usd.id}).status_code, 403)


class LimitesDeLaDemoTests(TestCase):
    """El seed deja límites que hacen visible la alerta en la demostración."""

    def _seed(self):
        call_command('seed_datos_demo', stdout=StringIO())

    def test_el_seed_carga_los_limites_y_no_pisa_los_que_cambio_el_administrador(self):
        self._seed()
        self.assertEqual(set(LimiteStock.objects.values_list('moneda__codigo', flat=True)), {'USD', 'EUR', 'PYG'})
        LimiteStock.objects.filter(moneda__codigo='USD').update(minimo=Decimal('1'), maximo=Decimal('2'))
        self._seed()
        usd = LimiteStock.objects.get(moneda__codigo='USD')
        self.assertEqual((usd.minimo, usd.maximo), (Decimal('1'), Decimal('2')))

    def test_la_caja_demo_arranca_sin_alertas(self):
        self._seed()
        self.assertEqual(services.alertas_de_stock(Caja.objects.get(cajero__username='cajero_demo')), [])

    def test_la_demo_cuenta_la_historia_de_la_alerta(self):
        """Comprar 13 USD baja el stock de dólares por debajo del mínimo (alerta y
        aviso); el cambio de 100 USD por euros lo devuelve a la normalidad."""
        self._seed()
        caja = Caja.objects.get(cajero__username='cajero_demo')
        cliente = Cliente.objects.get(nombre='Comercial Uno')
        services.registrar_operacion_presencial(
            caja=caja, usuario=caja.cajero, cliente=cliente, tipo='COMPRA',
            moneda_codigo='USD', cantidad=Decimal('13'),
        )
        (alerta,) = services.alertas_de_stock(caja)
        self.assertEqual((alerta['moneda'], alerta['nivel'], alerta['saldo']), ('USD', 'BAJO', Decimal('1847')))
        self.assertEqual(Notificaciones.objects.filter(usuario=caja.cajero, tipo='stock_billetes').count(), 1)

        services.registrar_operacion_presencial(
            caja=caja, usuario=caja.cajero, cliente=cliente, tipo='CAMBIO',
            moneda_codigo='USD', moneda_destino_codigo='EUR', cantidad=Decimal('100'),
        )
        self.assertEqual(services.alertas_de_stock(caja), [])
