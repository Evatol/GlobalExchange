from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import sesion
from .models import Cliente
from .serializers import (
    AsignacionUsuarioSerializer,
    ClienteResumenSerializer,
    ClienteSerializer,
    UsuarioResumenSerializer,
)


@login_required
def menu_principal_view(request):
    """Menú principal, con el selector de cliente activo (RF43)."""
    context = {
        'usuario': request.user,
        'mis_clientes': sesion.clientes_disponibles(request),
        'cliente_activo': sesion.get_cliente_activo(request),
    }
    return render(request, 'usuarios/menu_principal.html', context)


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

    Además, acciones dedicadas para la asignación de usuarios a un cliente (RF42):

    * ``GET  /api/usuarios/clientes/{id}/usuarios/``            -> lista los asignados.
    * ``POST /api/usuarios/clientes/{id}/asignar-usuario/``     -> ``{"usuario": <id>}``.
    * ``POST /api/usuarios/clientes/{id}/desasignar-usuario/``  -> ``{"usuario": <id>}``.
    """

    queryset = Cliente.objects.all().prefetch_related('usuarios')
    serializer_class = ClienteSerializer

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
