"""E4-193: la sesión identificada en una terminal de autoservicio solo accede a las pantallas
del autoservicio, y al cerrarla vuelve a la pantalla de inicio de la terminal."""
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.caja.models import Sucursal, Terminal
from apps.caja.services import crear_terminal

from . import sesion
from .oidc import provider_logout_url

User = get_user_model()

AUTOSERVICIO = '/api/caja/autoservicio/'
FUERA_DE_LA_TERMINAL = ('/api/usuarios/', '/api/transacciones/', '/api/facturacion/', '/api/caja/mi-caja/')


def _login(username, rol):
    user = User.objects.create_user(username, password='x')
    user.groups.add(Group.objects.get_or_create(name=rol)[0])
    return user


class TerminalSoloAutoservicioTests(TestCase):
    def setUp(self):
        sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')
        self.terminal = crear_terminal('Terminal MW', sucursal, Terminal.ACTIVA)
        self.inicio = reverse('terminal_inicio', args=[self.terminal.pk])
        self.web = Client()

    def entrar_en_modo_terminal(self, user):
        self.web.force_login(user)
        sesion_ = self.web.session
        sesion_[sesion.SESSION_KEY_TERMINAL] = self.terminal.pk
        sesion_.save()

    def test_una_sesion_identificada_en_la_terminal_no_sale_de_sus_pantallas(self):
        self.entrar_en_modo_terminal(_login('cli_mw', 'usuario_final'))

        for ruta in FUERA_DE_LA_TERMINAL + ('/admin/',):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.web.get(ruta).status_code, 403)

    def test_una_sesion_de_terminal_si_usa_las_pantallas_del_autoservicio_y_las_cotizaciones(self):
        self.entrar_en_modo_terminal(_login('cli_mw', 'usuario_final'))

        self.assertEqual(self.web.get(self.inicio).status_code, 200)
        self.assertEqual(self.web.get('/api/divisas/').status_code, 200)

    def test_tampoco_se_exceptua_a_los_superusuarios(self):
        self.entrar_en_modo_terminal(User.objects.create_superuser('root_mw', password='x'))
        self.assertEqual(self.web.get('/admin/').status_code, 403)

    def test_un_usuario_que_no_esta_en_una_terminal_navega_normalmente(self):
        self.web.force_login(_login('cli_normal', 'usuario_final'))

        self.assertEqual(self.web.get('/api/usuarios/').status_code, 200)
        self.assertEqual(self.web.get(self.inicio).status_code, 200)  # ver el inicio no lo restringe

    def test_el_inicio_de_la_terminal_no_pide_sesion(self):
        self.assertEqual(self.web.get(self.inicio).status_code, 200)
        self.assertEqual(self.web.get('/api/divisas/').status_code, 200)

    def test_el_login_y_el_logout_de_keycloak_siguen_disponibles(self):
        self.entrar_en_modo_terminal(_login('cli_mw', 'usuario_final'))
        # /oidc/authenticate/ redirige a Keycloak: lo que importa es que no sea un 403.
        self.assertNotEqual(self.web.get('/oidc/authenticate/').status_code, 403)


class SesionDeTerminalTests(TestCase):
    def _request(self, user=None):
        request = RequestFactory().get('/')
        request.session = {}
        if user is not None:
            request.user = user
        return request

    def test_terminal_activa_solo_cuenta_con_un_usuario_autenticado(self):
        request = self._request(User.objects.create_user('u1', password='x'))
        request.session[sesion.SESSION_KEY_TERMINAL] = 7
        self.assertEqual(sesion.terminal_activa(request), 7)

        request.user = type('Anonimo', (), {'is_authenticated': False})()
        self.assertIsNone(sesion.terminal_activa(request))

    def test_entrar_a_otra_terminal_olvida_el_cliente_elegido(self):
        request = self._request(User.objects.create_user('u2', password='x'))
        sesion.entrar_modo_terminal(request, 1)
        request.session[sesion.SESSION_KEY] = 55

        sesion.entrar_modo_terminal(request, 1)  # la misma: conserva la elección
        self.assertEqual(request.session[sesion.SESSION_KEY], 55)

        sesion.entrar_modo_terminal(request, 2)
        self.assertNotIn(sesion.SESSION_KEY, request.session)
        self.assertEqual(request.session[sesion.SESSION_KEY_TERMINAL], 2)

    def test_salir_limpia_la_marca_y_el_cliente(self):
        request = self._request(User.objects.create_user('u3', password='x'))
        sesion.entrar_modo_terminal(request, 3)
        request.session[sesion.SESSION_KEY] = 55

        sesion.salir_modo_terminal(request)

        self.assertEqual(request.session, {})


class CierreDeSesionDeLaTerminalTests(TestCase):
    """Al salir de una terminal (botón o inactividad) se vuelve a su pantalla de inicio."""

    def setUp(self):
        sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')
        self.terminal = crear_terminal('Terminal Logout', sucursal, Terminal.ACTIVA)

    def _destino(self, url):
        return parse_qs(urlparse(url).query)['post_logout_redirect_uri'][0]

    def test_en_una_terminal_el_logout_de_keycloak_vuelve_al_inicio_de_la_terminal(self):
        request = RequestFactory().get('/')
        request.user = User.objects.create_user('cli_lo', password='x')
        request.session = {sesion.SESSION_KEY_TERMINAL: self.terminal.pk, 'oidc_id_token': 'T'}

        url = provider_logout_url(request)

        self.assertEqual(
            self._destino(url), f'http://testserver/api/caja/autoservicio/{self.terminal.pk}/'
        )
        self.assertIn('id_token_hint=T', url)

    def test_fuera_de_una_terminal_el_logout_sigue_yendo_a_la_pagina_de_siempre(self):
        request = RequestFactory().get('/')
        request.user = User.objects.create_user('cli_lo2', password='x')
        request.session = {}
        self.assertEqual(self._destino(provider_logout_url(request)), 'http://testserver/')

    def test_el_boton_salir_cierra_la_sesion_y_manda_a_keycloak_con_destino_la_terminal(self):
        web = Client()
        web.force_login(User.objects.create_user('cli_lo3', password='x'))
        sesion_ = web.session
        sesion_[sesion.SESSION_KEY_TERMINAL] = self.terminal.pk
        sesion_.save()

        respuesta = web.post(reverse('oidc_logout'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(
            self._destino(respuesta['Location']),
            f'http://testserver/api/caja/autoservicio/{self.terminal.pk}/',
        )
        # La sesión local quedó cerrada: ya no es de quiosco.
        self.assertNotIn(sesion.SESSION_KEY_TERMINAL, web.session)
