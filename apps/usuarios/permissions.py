"""Permisos DRF basados en los roles de negocio sincronizados desde Keycloak
(ver ``apps.usuarios.backends.CustomOIDCBackend._sync_roles``).

Los roles llegan como grupos de Django con el mismo nombre que en Keycloak:
``administrador``, ``analista``, ``usuario_final`` (ver
``apps.usuarios.services.ROLES_NEGOCIO``). Un superusuario (rol
``administrador``) pasa cualquier chequeo, por convención estándar de Django.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

ADMINISTRADOR = 'administrador'
ANALISTA = 'analista'
USUARIO_FINAL = 'usuario_final'


def tiene_rol(user, roles):
    """True si el usuario está autenticado y tiene alguno de los roles dados
    (o es superusuario, que siempre pasa)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


class PermiteEscrituraSoloA(BasePermission):
    """Lectura (GET/HEAD/OPTIONS) libre para cualquiera; escritura
    (POST/PUT/PATCH/DELETE y acciones custom) solo para los roles listados
    en ``roles_permitidos`` de la subclase."""

    roles_permitidos = ()

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return tiene_rol(request.user, self.roles_permitidos)


class SoloAdministradorOAnalistaEscriben(PermiteEscrituraSoloA):
    """Monedas y Cotizaciones (RF21/RF22): cualquiera consulta, solo
    administrador o analista pueden crear/editar/desactivar/reactivar."""

    roles_permitidos = (ADMINISTRADOR, ANALISTA)


class SoloAdministradorEscribe(PermiteEscrituraSoloA):
    """Catálogo de métodos de pago: cualquiera consulta, solo administrador
    lo administra."""

    roles_permitidos = (ADMINISTRADOR,)


class ClientesPermission(BasePermission):
    """CRUD de Clientes: lectura para administrador/analista, escritura solo
    para administrador. Ningún acceso para usuario_final (opera sobre sus
    propios clientes vía /mis-clientes/ y /cliente-activo/, no por acá)."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
        return tiene_rol(request.user, (ADMINISTRADOR,))
