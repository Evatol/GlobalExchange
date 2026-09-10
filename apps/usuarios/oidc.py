"""Helpers OIDC para el cierre de sesión contra Keycloak (RP-initiated logout)."""

from urllib.parse import urlencode

from django.conf import settings


def provider_logout_url(request):
    """Devuelve la URL de logout de Keycloak a la que redirigir tras el logout local.

    ``mozilla-django-oidc`` la invoca desde ``OIDCLogoutView.post()`` (setting
    ``OIDC_OP_LOGOUT_URL_METHOD``). El objetivo es cerrar también la sesión SSO en
    Keycloak y volver a ``LOGOUT_REDIRECT_URL``; como ese destino no está logueado,
    el usuario termina viendo de nuevo la pantalla de login de Keycloak.

    Se manda ``id_token_hint`` cuando está disponible (logout sin pantalla de
    confirmación); si no, se manda ``client_id`` para que Keycloak valide el
    ``post_logout_redirect_uri``.
    """
    redirect_uri = request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL)
    params = {'post_logout_redirect_uri': redirect_uri}

    id_token = request.session.get('oidc_id_token')
    if id_token:
        params['id_token_hint'] = id_token
    else:
        params['client_id'] = settings.OIDC_RP_CLIENT_ID

    return f'{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}'
