"""E4-195: el cierre por inactividad está registrado en la aplicación (no solo
funciona el middleware por separado, que prueban ``tests_inactividad``)."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

User = get_user_model()


class InactividadRegistradaTests(TestCase):
    def test_el_middleware_esta_en_la_configuracion(self):
        self.assertIn('apps.usuarios.inactividad.InactividadMiddleware', settings.MIDDLEWARE)

    def test_el_middleware_va_despues_de_la_autenticacion(self):
        """Necesita ``request.user``, así que tiene que estar después de
        ``AuthenticationMiddleware``."""
        orden = settings.MIDDLEWARE
        self.assertGreater(
            orden.index('apps.usuarios.inactividad.InactividadMiddleware'),
            orden.index('django.contrib.auth.middleware.AuthenticationMiddleware'),
        )

    def test_un_usuario_autenticado_recibe_el_script_en_las_paginas_html(self):
        cliente = Client()
        cliente.force_login(User.objects.create_user('inactivo_fact', password='x'))
        resp = cliente.get('/api/usuarios/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ge_ultima_actividad')
        self.assertContains(resp, '"limite": 300')
        self.assertContains(resp, '"aviso": 30')

    def test_una_pagina_publica_no_recibe_el_script(self):
        resp = Client().get('/api/divisas/')
        self.assertNotContains(resp, 'ge_ultima_actividad')

    def test_la_sesion_de_django_vence_poco_despues_del_limite(self):
        self.assertGreater(settings.SESSION_COOKIE_AGE, settings.INACTIVIDAD_SEGUNDOS)
        self.assertLessEqual(
            settings.SESSION_COOKIE_AGE,
            settings.INACTIVIDAD_SEGUNDOS + settings.INACTIVIDAD_AVISO_SEGUNDOS + 60,
        )
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
