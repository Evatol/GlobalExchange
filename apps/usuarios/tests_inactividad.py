"""Pruebas del cierre de sesión por inactividad (E4-195)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.usuarios.inactividad import InactividadMiddleware

HTML = '<html><body><p>hola</p></body></html>'


def _pedido(usuario):
    request = RequestFactory().get('/')
    request.user = usuario
    return request


def _usuario_autenticado():
    # Sin guardar en la base: alcanza con que is_authenticated sea True.
    return get_user_model()(username='ana')


class InactividadMiddlewareTests(SimpleTestCase):

    def _aplicar(self, usuario, respuesta):
        middleware = InactividadMiddleware(lambda request: respuesta)
        return middleware(_pedido(usuario))

    def test_inyecta_el_script_a_un_usuario_autenticado(self):
        response = self._aplicar(_usuario_autenticado(), HttpResponse(HTML))
        contenido = response.content.decode()
        self.assertIn('ge_ultima_actividad', contenido)
        self.assertIn('/oidc/logout/', contenido)
        # El script queda antes del cierre del body, que sigue una sola vez.
        self.assertEqual(contenido.count('</body>'), 1)
        self.assertLess(contenido.index('ge_ultima_actividad'), contenido.index('</body>'))

    def test_no_inyecta_nada_a_un_usuario_anonimo(self):
        response = self._aplicar(AnonymousUser(), HttpResponse(HTML))
        self.assertEqual(response.content.decode(), HTML)

    def test_no_toca_respuestas_que_no_son_html(self):
        response = self._aplicar(_usuario_autenticado(), JsonResponse({'ok': True}))
        self.assertNotIn('ge_ultima_actividad', response.content.decode())

    def test_no_toca_respuestas_que_no_son_200(self):
        response = self._aplicar(_usuario_autenticado(), HttpResponse(HTML, status=403))
        self.assertEqual(response.content.decode(), HTML)

    def test_no_toca_html_sin_body(self):
        response = self._aplicar(_usuario_autenticado(), HttpResponse('<p>fragmento</p>'))
        self.assertEqual(response.content.decode(), '<p>fragmento</p>')

    @override_settings(INACTIVIDAD_SEGUNDOS=120, INACTIVIDAD_AVISO_SEGUNDOS=20)
    def test_usa_los_tiempos_configurados(self):
        contenido = self._aplicar(_usuario_autenticado(), HttpResponse(HTML)).content.decode()
        self.assertIn('"limite": 120', contenido)
        self.assertIn('"aviso": 20', contenido)

    @override_settings(INACTIVIDAD_SEGUNDOS=10, INACTIVIDAD_AVISO_SEGUNDOS=60)
    def test_el_aviso_nunca_supera_el_limite(self):
        contenido = self._aplicar(_usuario_autenticado(), HttpResponse(HTML)).content.decode()
        self.assertIn('"aviso": 10', contenido)

    def test_actualiza_content_length(self):
        respuesta = HttpResponse(HTML)
        respuesta['Content-Length'] = str(len(HTML))
        response = self._aplicar(_usuario_autenticado(), respuesta)
        self.assertEqual(int(response['Content-Length']), len(response.content))