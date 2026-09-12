from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services, sesion
from .models import Cliente, Usuario
from .permissions import ADMINISTRADOR, ANALISTA, ClientesPermission, tiene_rol
from .serializers import (
    AsignacionUsuarioSerializer,
    ClienteResumenSerializer,
    ClienteSerializer,
    PerfilSerializer,
    UsuarioResumenSerializer,
)


def _es_administrador(user):
    """El rol 'administrador' de Keycloak se refleja como is_staff
    (ver CustomOIDCBackend._sync_roles), así que alcanza con chequear eso:
    no depende de ningún username en particular."""
    return user.is_authenticated and user.is_staff


@login_required
def menu_principal_view(request):
    """Menú principal, con el selector de cliente activo (RF43) y los
    accesos a cada CRUD según el rol de quien inició sesión."""
    context = {
        'usuario': request.user,
        'mis_clientes': sesion.clientes_disponibles(request),
        'cliente_activo': sesion.get_cliente_activo(request),
        'es_administrador': _es_administrador(request.user),
        'puede_gestionar_divisas': tiene_rol(request.user, (ADMINISTRADOR, ANALISTA)),
    }
    return render(request, 'usuarios/menu_principal.html', context)


@login_required
def mi_perfil_view(request):
    """RF9/RF10: cualquier usuario logueado (sin importar su rol) actualiza
    sus propios datos personales complementarios (nombres, apellidos,
    teléfono, dirección). El usuario y el correo se muestran pero no se
    pueden editar acá: quedan bloqueados para garantizar la identificación
    única (RF10) y porque son los que vienen de Keycloak."""
    perfil = sesion.usuario_negocio(request)
    if perfil is None:
        raise PermissionDenied('No se encontró tu perfil de usuario.')

    error = None
    exito = False
    if request.method == 'POST':
        serializer = PerfilSerializer(instance=perfil, data=request.POST, partial=True)
        if serializer.is_valid():
            serializer.save()
            exito = True
        else:
            error = ' '.join(
                str(msg) for errores in serializer.errors.values() for msg in errores
            )

    context = {
        'usuario': request.user,
        'perfil': perfil,
        'error': error,
        'exito': exito,
    }
    return render(request, 'usuarios/mi_perfil.html', context)


@login_required
def gestion_roles_view(request):
    """Pantalla para que un administrador asigne el rol de negocio de cada
    usuario del sistema (RF46 desasignar / RF48 asignar)."""
    if not _es_administrador(request.user):
        raise PermissionDenied('Esta sección es solo para administradores.')
    context = {
        'usuario': request.user,
        'usuarios': services.listar_usuarios_con_roles(),
        'roles_disponibles': services.ROLES_NEGOCIO,
    }
    return render(request, 'usuarios/gestion_roles.html', context)


@login_required
def asignar_rol_view(request):
    """Aplica, desde el formulario de la pantalla de gestión de roles, el
    rol elegido para un usuario puntual."""
    if not _es_administrador(request.user):
        raise PermissionDenied('Esta sección es solo para administradores.')
    if request.method == 'POST':
        username = request.POST.get('username')
        rol = request.POST.get('rol')
        if username and rol in services.ROLES_NEGOCIO:
            services.asignar_rol_negocio(username, rol)
    return redirect('gestion_roles')


@login_required
def gestion_clientes_view(request):
    """Pantalla propia del CRUD de Clientes (E4-125), con la asociación de
    usuarios (RF42) en la misma pantalla. Reutiliza ``ClienteSerializer``
    para no duplicar validaciones (razón social obligatoria para jurídica,
    límites no negativos, etc.).

    Consulta: administrador o analista. Crear/editar/activar/desactivar y
    asociar/desasociar usuarios: solo administrador.
    """
    if not tiene_rol(request.user, (ADMINISTRADOR, ANALISTA)):
        raise PermissionDenied('Esta sección es solo para administrador o analista.')

    puede_escribir = tiene_rol(request.user, (ADMINISTRADOR,))

    error = None
    if request.method == 'POST':
        if not puede_escribir:
            raise PermissionDenied('Solo un administrador puede crear clientes.')
        serializer = ClienteSerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_clientes')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    context = {
        'usuario': request.user,
        'clientes': Cliente.objects.all().prefetch_related('usuarios').order_by('nombre'),
        'todos_usuarios': Usuario.objects.all().order_by('username'),
        'puede_escribir': puede_escribir,
        'tipo_choices': Cliente.TIPO_CHOICES,
        'categoria_choices': Cliente.CATEGORIA_CHOICES,
        'preferencia_choices': Cliente.PREFERENCIA_TIPO_CAMBIO_CHOICES,
        'error': error,
    }
    return render(request, 'usuarios/gestion_clientes.html', context)


@login_required
def cliente_editar_view(request, pk):
    """Edita los datos de un cliente existente (E4-125): nombre, documento,
    tipo, razón social, categoría, límites, frecuencia y preferencia de
    cambio. Reutiliza ``ClienteSerializer`` (misma validación que el alta:
    razón social obligatoria si es jurídica, límites no negativos). No toca
    los usuarios asociados (eso se maneja aparte, en la pantalla de
    listado). Solo administrador."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise PermissionDenied('Solo un administrador puede editar clientes.')

    cliente = Cliente.objects.filter(pk=pk).first()
    if cliente is None:
        return redirect('gestion_clientes')

    error = None
    if request.method == 'POST':
        serializer = ClienteSerializer(instance=cliente, data=request.POST, partial=True)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_clientes')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    context = {
        'usuario': request.user,
        'cliente': cliente,
        'tipo_choices': Cliente.TIPO_CHOICES,
        'categoria_choices': Cliente.CATEGORIA_CHOICES,
        'preferencia_choices': Cliente.PREFERENCIA_TIPO_CAMBIO_CHOICES,
        'error': error,
    }
    return render(request, 'usuarios/cliente_editar.html', context)


@login_required
def cliente_toggle_view(request, pk):
    """Activa/desactiva un cliente (borrado lógico) desde la pantalla de gestión."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise PermissionDenied('Solo un administrador puede activar/desactivar clientes.')
    cliente = Cliente.objects.filter(pk=pk).first()
    if cliente is not None:
        cliente.estado = not cliente.estado
        cliente.save()
    return redirect('gestion_clientes')


@login_required
def cliente_asignar_usuario_view(request, pk):
    """Asocia un usuario existente a un cliente (RF42), desde la pantalla de gestión."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise PermissionDenied('Solo un administrador puede asociar usuarios.')
    cliente = Cliente.objects.filter(pk=pk).first()
    if cliente is not None and request.method == 'POST':
        usuario = Usuario.objects.filter(pk=request.POST.get('usuario')).first()
        if usuario is not None:
            cliente.asociar_usuario(usuario)
    return redirect('gestion_clientes')


@login_required
def cliente_desasignar_usuario_view(request, pk, usuario_id):
    """Quita la asociación de un usuario a un cliente (RF42)."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise PermissionDenied('Solo un administrador puede desasociar usuarios.')
    cliente = Cliente.objects.filter(pk=pk).first()
    usuario = Usuario.objects.filter(pk=usuario_id).first()
    if cliente is not None and usuario is not None:
        cliente.desasociar_usuario(usuario)
    return redirect('gestion_clientes')


@login_required
def seleccionar_cliente_view(request):
    """Cambia el cliente activo desde el formulario del menú (RF43)."""
    if request.method == 'POST':
        try:
            sesion.set_cliente_activo(request, request.POST.get('cliente'))
        except PermissionDenied:
            pass  # entrada inválida: se ignora y se vuelve al menú
    return redirect('menu_principal')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def mis_clientes(request):
    """Clientes a los que el usuario está asociado, y cuál está activo (RF43)."""
    return Response({
        'clientes': ClienteResumenSerializer(
            sesion.clientes_disponibles(request), many=True
        ).data,
        'cliente_activo': getattr(sesion.get_cliente_activo(request), 'pk', None),
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def cliente_activo(request):
    """GET: cliente activo actual. POST ``{"cliente": <id>}``: lo cambia (RF43)."""
    if request.method == 'POST':
        try:
            cliente = sesion.set_cliente_activo(request, request.data.get('cliente'))
        except PermissionDenied as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(ClienteResumenSerializer(cliente).data)

    activo = sesion.get_cliente_activo(request)
    if activo is None:
        return Response({'detail': 'No hay cliente activo.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(ClienteResumenSerializer(activo).data)


class ClienteViewSet(viewsets.ModelViewSet):
    """CRUD completo de clientes (E4-125).

    Expone listar, crear, ver detalle, editar y eliminar sobre ``/api/usuarios/clientes/``.
    Permite filtrar por ``tipo``, ``categoria``, ``estado`` y
    ``preferencia_tipo_cambio`` vía querystring para la segmentación de datos.

    Permisos: consulta para ``administrador``/``analista``; alta, edición,
    eliminación y asignación de usuarios solo para ``administrador``.
    ``usuario_final`` no tiene acceso acá (opera sobre sus propios clientes
    vía ``/mis-clientes/`` y ``/cliente-activo/``).

    Además, acciones dedicadas para la asignación de usuarios a un cliente (RF42):

    * ``GET  /api/usuarios/clientes/{id}/usuarios/``            -> lista los asignados.
    * ``POST /api/usuarios/clientes/{id}/asignar-usuario/``     -> ``{"usuario": <id>}``.
    * ``POST /api/usuarios/clientes/{id}/desasignar-usuario/``  -> ``{"usuario": <id>}``.
    """

    queryset = Cliente.objects.all().prefetch_related('usuarios')
    serializer_class = ClienteSerializer
    permission_classes = [ClientesPermission]

    FILTROS = ('tipo', 'categoria', 'estado', 'preferencia_tipo_cambio')

    def get_queryset(self):
        queryset = super().get_queryset()
        for campo in self.FILTROS:
            valor = self.request.query_params.get(campo)
            if valor in (None, ''):
                continue
            if campo == 'estado':
                valor = valor.lower() in ('1', 'true', 'si', 'sí')
            queryset = queryset.filter(**{campo: valor})
        return queryset

    # --- Asignación de usuarios <-> cliente (RF42) --------------------- #

    @action(detail=True, methods=['get'])
    def usuarios(self, request, pk=None):
        """Lista los usuarios asignados a este cliente."""
        cliente = self.get_object()
        data = UsuarioResumenSerializer(cliente.usuarios.all(), many=True).data
        return Response(data)

    @action(detail=True, methods=['post'], url_path='asignar-usuario')
    def asignar_usuario(self, request, pk=None):
        """Asigna un usuario a este cliente. Idempotente."""
        cliente = self.get_object()
        cliente.asociar_usuario(self._usuario_de(request))
        return Response(self.get_serializer(cliente).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='desasignar-usuario')
    def desasignar_usuario(self, request, pk=None):
        """Quita un usuario de este cliente. Idempotente."""
        cliente = self.get_object()
        cliente.desasociar_usuario(self._usuario_de(request))
        return Response(self.get_serializer(cliente).data, status=status.HTTP_200_OK)

    @staticmethod
    def _usuario_de(request):
        serializer = AsignacionUsuarioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data['usuario']
