"""Helpers OIDC para el cierre de sesión contra Keycloak (RP-initiated logout)."""

from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse

from . import sesion


def provider_logout_url(request):
    """Devuelve la URL de logout de Keycloak a la que redirigir tras el logout local.

    ``mozilla-django-oidc`` la invoca desde ``OIDCLogoutView.post()`` (setting
    ``OIDC_OP_LOGOUT_URL_METHOD``). El objetivo es cerrar también la sesión SSO en
    Keycloak y volver a ``LOGOUT_REDIRECT_URL``; como ese destino no está logueado,
    el usuario termina viendo de nuevo la pantalla de login de Keycloak. En una sesión
    de quiosco vuelve a la pantalla de inicio de la terminal.

    Se manda ``id_token_hint`` cuando está disponible (logout sin pantalla de
    confirmación); si no, se manda ``client_id`` para que Keycloak valide el
    ``post_logout_redirect_uri``.
    """
    terminal_id = sesion.terminal_activa(request)
    if terminal_id is not None:
        # Sesión de quiosco (E4-193): al cerrar, ya sea por el botón o por inactividad,
        # se vuelve a la pantalla de inicio de la terminal, lista para el próximo cliente.
        return url_de_cierre_de_sesion(request, reverse('terminal_inicio', args=[terminal_id]))
    return url_de_cierre_de_sesion(request, settings.LOGOUT_REDIRECT_URL)


def url_de_cierre_de_sesion(request, destino):
    """URL de logout de Keycloak que, al terminar, vuelve a ``destino`` (una ruta de la
    aplicación). La usa el autoservicio para volver a su pantalla de inicio al cerrar la
    sesión de un cliente. Hay que pedirla antes de cerrar la sesión local, porque el
    ``id_token`` sale de ella."""
    redirect_uri = request.build_absolute_uri(destino)
    params = {'post_logout_redirect_uri': redirect_uri}

    id_token = request.session.get('oidc_id_token')
    if id_token:
        params['id_token_hint'] = id_token
    else:
        params['client_id'] = settings.OIDC_RP_CLIENT_ID

    return f'{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}'


def account_console_url(request):
    """URL de la Account Console nativa de Keycloak.

    La contraseña del usuario vive en Keycloak, no en Django (el modelo
    ``Usuario`` no tiene ningún campo de contraseña), así que el cambio de
    contraseña (RF9) no se implementa con un formulario propio: se manda al
    usuario a la pantalla nativa de Keycloak para eso, que ya valida la
    contraseña actual y aplica la política de contraseñas del realm.
    """
    base = settings.KEYCLOAK_PUBLIC_URL.rstrip('/')
    referrer_uri = request.build_absolute_uri(reverse('menu_principal'))
    params = urlencode({
        'referrer': settings.OIDC_RP_CLIENT_ID,
        'referrer_uri': referrer_uri,
    })
    return f'{base}/realms/{settings.KEYCLOAK_REALM}/account/?{params}'
