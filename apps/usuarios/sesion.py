"""Cliente activo de la sesión (RF43).

Un usuario asociado a varios clientes elige sobre cuál opera. La elección vive
en la sesión (``request.session['cliente_activo_id']``). Si el usuario tiene un
solo cliente, se selecciona automáticamente.
"""

from django.core.exceptions import PermissionDenied

from .models import Cliente, Usuario

SESSION_KEY = "cliente_activo_id"


def usuario_negocio(request):
    """Devuelve el ``Usuario`` (modelo de negocio) del request, o ``None``.

    El backend OIDC crea/actualiza este registro en cada login
    (``CustomOIDCBackend._sync_usuario_negocio``).
    """
    if not request.user.is_authenticated:
        return None
    return Usuario.objects.filter(username=request.user.username).first()


def clientes_disponibles(request):
    """Clientes activos a los que el usuario está asociado (RF42)."""
    usuario = usuario_negocio(request)
    if usuario is None:
        return Cliente.objects.none()
    return usuario.clientes.filter(estado=True).order_by("nombre")


def get_cliente_activo(request):
    """Cliente activo de la sesión.

    Valida que el usuario siga asociado y que el cliente siga activo. Si no hay
    uno elegido pero el usuario tiene exactamente uno disponible, lo fija.
    """
    disponibles = clientes_disponibles(request)
    activo_id = request.session.get(SESSION_KEY)

    if activo_id is not None:
        cliente = disponibles.filter(pk=activo_id).first()
        if cliente is not None:
            return cliente
        request.session.pop(SESSION_KEY, None)

    if disponibles.count() == 1:
        cliente = disponibles.first()
        request.session[SESSION_KEY] = cliente.pk
        return cliente

    return None


def set_cliente_activo(request, cliente_id):
    """Fija el cliente activo. Lanza ``PermissionDenied`` si el usuario no está
    asociado a ese cliente (o el cliente está inactivo)."""
    cliente = clientes_disponibles(request).filter(pk=cliente_id).first()
    if cliente is None:
        raise PermissionDenied(
            "No estás asociado a ese cliente o el cliente está inactivo."
        )
    request.session[SESSION_KEY] = cliente.pk
    return cliente
