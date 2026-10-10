from django.core.exceptions import PermissionDenied

from .permissions import es_cajero


class CajeroSoloCajaMiddleware:
    """Un usuario con rol cajero solo accede al módulo de caja (RF109 / E4-98);
    cualquier otra pantalla responde 403. Los superusuarios (administrador) no
    se restringen.

    Se permite además ``/oidc/`` (login, callback y logout con Keycloak) y el
    menú principal exacto, para que el login no termine en un 403.
    """

    PREFIJOS_PERMITIDOS = ('/api/caja/', '/oidc/')
    RUTAS_EXACTAS_PERMITIDAS = ('/api/usuarios/',)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if es_cajero(user) and not user.is_superuser:
            ruta = request.path
            permitida = (
                ruta in self.RUTAS_EXACTAS_PERMITIDAS
                or ruta.startswith(self.PREFIJOS_PERMITIDOS)
            )
            if not permitida:
                raise PermissionDenied('El rol cajero solo puede acceder al módulo de caja.')
        return self.get_response(request)
