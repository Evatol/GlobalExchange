from decimal import Decimal
from django.contrib.auth.models import User as DjangoUser
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from apps.divisas.models import Moneda, TasaCambio
from apps.divisas.services import procesar_cambio_cotizacion
from apps.notificaciones.models import Notificaciones
from apps.usuarios.models import Usuario


class NotificacionesVariacionPrecioTests(TestCase): # E4-32 y E4-33
    def setUp(self):
        # Crear monedas
        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólar', estado=True)
        self.moneda_eur = Moneda.objects.create(codigo='EUR', nombre='Euro', estado=True)

        # Crear usuarios
        self.user_con_favorita = Usuario.objects.create(
            username='romina',
            email='romina@example.com',
            nombres='Romina',
            apellidos='Test',
            telefono='000000000',
            direccion='Dirección de prueba',
        )
        self.user_con_favorita.monedas_favoritas.add(self.moneda_usd)

        self.user_sin_favorita = Usuario.objects.create(
            username='visitante',
            email='visitante@example.com',
            nombres='Visitante',
            apellidos='Test',
            telefono='000000001',
            direccion='Dirección de prueba',
        )

    def test_variacion_menor_o_igual_a_uno_por_ciento_no_genera_aviso(self):
        # Cotización inicial
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.00'),
            tasa_venta=Decimal('105.00'),
            estado=True
        )
        # Cotización nueva con un cambio del 0.5% (menor al umbral de 1.0%)
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.50'),
            tasa_venta=Decimal('105.50'),
            estado=True
        )

        procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # No debe crearse ninguna notificación ni correo
        self.assertEqual(Notificaciones.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_variacion_mayor_a_uno_por_ciento_genera_aviso_y_correo_para_favoritos(self):
        # Cotización inicial
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.00'),
            tasa_venta=Decimal('105.00'),
            estado=True
        )
        # Cotización nueva con un cambio mayor al 1% (ej. 3%)
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('103.00'),
            tasa_venta=Decimal('108.00'),
            estado=True
        )

        # Capturar y ejecutar callbacks de transacción on_commit para los correos
        with self.captureOnCommitCallbacks(execute=True):
            procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # Debe crearse una notificación únicamente para el usuario con la moneda en favorita
        notificaciones = Notificaciones.objects.all()
        self.assertEqual(notificaciones.count(), 1)
        self.assertEqual(notificaciones[0].usuario, self.user_con_favorita)
        self.assertIn('USD', notificaciones[0].titulo)

        # Verificar que se envió el correo electrónico correspondiente (E4-33)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('USD', mail.outbox[0].subject)
        self.assertIn('romina@example.com', mail.outbox[0].to)
        self.assertIn('100.00', mail.outbox[0].body)

    def test_endpoint_consultar_notificaciones_nuevas(self):
        # Crear una notificación directa para romina
        Notificaciones.objects.create(
            usuario=self.user_con_favorita,
            titulo='Variación Relevante: USD',
            mensaje='La cotización ha variado.',
            tipo='variacion_cotizacion',
            leida=False
        )

        # Autenticar como romina y consultar la API
        DjangoUser.objects.create_user(username='romina', password='password123')
        self.client.login(username='romina', password='password123')
        url = reverse('api_notificaciones_nuevas')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['notificaciones']), 1)
        self.assertEqual(data['notificaciones'][0]['titulo'], 'Variación Relevante: USD')

    def test_usuario_sin_favorita_no_ve_ni_recibe_avisos(self):
        # Cotización con gran variación
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_eur,
            tasa_compra=Decimal('500.00'),
            tasa_venta=Decimal('510.00'),
            estado=True
        )
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_eur,
            tasa_compra=Decimal('550.00'),
            tasa_venta=Decimal('560.00'),
            estado=True
        )

        with self.captureOnCommitCallbacks(execute=True):
            procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # Ningún usuario tiene EUR como favorita, no debe haber notificaciones ni correos
        self.assertEqual(Notificaciones.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

class MarcarNotificacionLeidaTests(TestCase):
    """Los avisos de cotización se muestran hasta que el usuario los cierra: al
    cerrarlos se marcan como leídos y no vuelven a aparecer en otra pantalla ni
    en la próxima visita (antes se mostraban de nuevo cada vez)."""

    def setUp(self):
        self.usuario = Usuario.objects.create(
            username='cli_notif', email='cn@example.com', nombres='C', apellidos='N',
            telefono='1', direccion='x',
        )
        self.login = DjangoUser.objects.create_user('cli_notif')
        self.otro = Usuario.objects.create(
            username='otro_notif', email='on@example.com', nombres='O', apellidos='N',
            telefono='2', direccion='x',
        )
        self.aviso = Notificaciones.objects.create(
            usuario=self.usuario, titulo='Variación Relevante: USD', mensaje='subió', tipo='variacion_cotizacion',
        )
        self.client.force_login(self.login)

    def _url(self, pk):
        return reverse('api_notificacion_leida', args=[pk])

    def _pendientes(self):
        r = self.client.get(reverse('api_notificaciones_nuevas'))
        return [n['id'] for n in r.json()['notificaciones']]

    def test_el_aviso_se_repite_hasta_que_se_lo_marca_como_leido(self):
        self.assertEqual(self._pendientes(), [self.aviso.pk])
        self.assertEqual(self._pendientes(), [self.aviso.pk])  # consultar no lo gasta

        resp = self.client.post(self._url(self.aviso.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'id': self.aviso.pk, 'leida': True})
        self.aviso.refresh_from_db()
        self.assertTrue(self.aviso.leida)
        self.assertEqual(self._pendientes(), [])

    def test_solo_se_marca_lo_propio(self):
        ajeno = Notificaciones.objects.create(
            usuario=self.otro, titulo='x', mensaje='y', tipo='variacion_cotizacion',
        )
        self.assertEqual(self.client.post(self._url(ajeno.pk)).status_code, 404)
        ajeno.refresh_from_db()
        self.assertFalse(ajeno.leida)

    def test_notificacion_inexistente(self):
        self.assertEqual(self.client.post(self._url(99999)).status_code, 404)

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get(self._url(self.aviso.pk)).status_code, 405)
        self.aviso.refresh_from_db()
        self.assertFalse(self.aviso.leida)

    def test_requiere_login(self):
        self.client.logout()
        self.assertEqual(self.client.post(self._url(self.aviso.pk)).status_code, 302)
        self.aviso.refresh_from_db()
        self.assertFalse(self.aviso.leida)

    def test_un_usuario_sin_perfil_de_negocio_no_marca_nada(self):
        sin_perfil = DjangoUser.objects.create_user('sin_perfil_notif')
        self.client.force_login(sin_perfil)
        self.assertEqual(self.client.post(self._url(self.aviso.pk)).status_code, 404)

    def test_la_pantalla_de_operar_tambien_muestra_los_avisos(self):
        """Antes solo el menú principal consultaba los avisos."""
        resp = self.client.get('/api/transacciones/gestion/operar/')
        self.assertContains(resp, 'id="contenedor-alertas-divisas"')
        self.assertContains(resp, reverse('api_notificaciones_nuevas'))
        resp_menu = self.client.get(reverse('menu_principal'))
        self.assertContains(resp_menu, 'id="contenedor-alertas-divisas"')
        # y los comentarios del parcial no se imprimen en la página del cliente
        for pagina in (resp, resp_menu):
            self.assertNotContains(pagina, '{#')
            self.assertNotContains(pagina, 'Se incluye en las pantallas del')

    def test_el_aviso_no_se_arma_con_innerhtml(self):
        """El texto del aviso incluye el nombre de la moneda, que carga un usuario:
        no puede interpretarse como HTML en el navegador de quien lo recibe."""
        from django.template.loader import render_to_string
        html = render_to_string('usuarios/_notificaciones_tiempo_real.html', request=None)
        self.assertNotIn('innerHTML', html)
        self.assertIn('textContent', html)
        self.assertIn('close.bs.alert', html)  # cerrar el aviso lo marca como leído


class CorreoFallidoNoRompeLaCotizacionTests(TestCase):
    """Si falla el envío del correo, la cotización se guarda igual y el problema
    queda en el log (antes se imprimía con ``print``)."""

    def test_el_error_de_correo_se_registra_en_el_log(self):
        from unittest import mock
        usd = Moneda.objects.create(codigo='USD', nombre='Dólar', estado=True)
        usuario = Usuario.objects.create(
            username='fav', email='fav@example.com', nombres='F', apellidos='V', telefono='1', direccion='x',
        )
        usuario.monedas_favoritas.add(usd)
        anterior = TasaCambio.objects.create(moneda=usd, tasa_compra=Decimal('100'), tasa_venta=Decimal('105'), estado=True)
        nueva = TasaCambio.objects.create(moneda=usd, tasa_compra=Decimal('120'), tasa_venta=Decimal('126'), estado=True)

        with mock.patch('apps.divisas.services.send_mail', side_effect=OSError('SMTP caído')):
            with self.assertLogs('apps.divisas.services', level='WARNING') as log:
                with self.captureOnCommitCallbacks(execute=True):
                    procesar_cambio_cotizacion(nueva, anterior)

        self.assertIn('No se pudo enviar el correo a fav@example.com', log.output[0])
        self.assertIn('SMTP caído', log.output[0])
        self.assertEqual(Notificaciones.objects.filter(usuario=usuario).count(), 1)  # el aviso interno sí quedó


class PlantillasSinComentariosRotosTests(TestCase):
    """En Django, ``{# ... #}`` solo comenta dentro de una línea: si un comentario
    ocupa varias, se imprime como texto en la página. Para varias líneas hay que
    usar ``{% comment %}``."""

    def test_ninguna_plantilla_tiene_un_comentario_de_una_linea_abierto_sin_cerrar(self):
        from pathlib import Path
        from django.conf import settings
        rotos = []
        for plantilla in Path(settings.BASE_DIR, 'apps').rglob('*.html'):
            for n, linea in enumerate(plantilla.read_text().splitlines(), 1):
                if '{#' in linea and '#}' not in linea:
                    rotos.append(f'{plantilla.relative_to(settings.BASE_DIR)}:{n}')
        self.assertEqual(rotos, [], 'Usá {% comment %} para comentarios de varias líneas.')
