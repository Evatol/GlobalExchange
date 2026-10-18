from django.core.exceptions import PermissionDenied

from . import sesion
from .permissions import es_cajero


class CajeroSoloCajaMiddleware:
    """Un usuario con rol cajero solo accede al módulo de caja (RF109 / E4-98);
    cualquier otra pantalla responde 403. Los superusuarios (administrador) no
    se restringen.

    Se permite además ``/oidc/`` (login, callback y logout con Keycloak), el
    menú principal exacto, para que el login no termine en un 403, y
    ``/api/notificaciones/``: el cajero recibe avisos propios (por ejemplo, de
    stock de billetes, RF107) y esa API solo devuelve y marca los suyos.
    """

    PREFIJOS_PERMITIDOS = ('/api/caja/', '/oidc/', '/api/notificaciones/')
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


class TerminalSoloAutoservicioMiddleware:
    """Una sesión de quiosco solo accede a las pantallas del autoservicio (E4-193): lo es la
    de cualquier usuario que se identificó en una terminal (``sesion.terminal_activa``,
    que fija ``terminal_ingreso``). Cualquier otra pantalla responde 403, para que quien
    opera en la terminal no pueda navegar al resto del sistema.

    Se permite además ``/oidc/`` (login y logout con Keycloak) y las cotizaciones públicas
    (``/api/divisas/``). Quien no está autenticado no se restringe: el inicio del
    autoservicio es público. Tampoco se exceptúa a los superusuarios: quien se identificó en
    una terminal sale con "Salir" (o por inactividad), no navegando.
    """

    PREFIJOS_PERMITIDOS = ('/api/caja/autoservicio/', '/oidc/', '/api/divisas/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if sesion.terminal_activa(request) is not None and not request.path.startswith(
            self.PREFIJOS_PERMITIDOS
        ):
            raise PermissionDenied(
                'Esta sesión es de una terminal de autoservicio: solo puede usar '
                'las pantallas de la terminal.'
            )
        return self.get_response(request)
