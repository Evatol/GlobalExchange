from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.usuarios import sesion
from apps.usuarios.permissions import (
    ADMINISTRADOR,
    ANALISTA,
    SoloAdministradorEscribe,
    tiene_rol,
)

from .models import MedioPagoCliente, MetodoPago
from .serializers import MedioPagoClienteSerializer, MetodoPagoSerializer


class _BorradoLogicoMixin:
    """DELETE desactiva el registro en vez de eliminarlo; ``POST .../activar/`` lo reactiva."""

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.desactivar()
        return Response(
            {'detail': f'{obj} desactivado correctamente.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        obj = self.get_object()
        obj.activar()
        return Response({'detail': f'{obj} activado.'})


class MetodoPagoViewSet(_BorradoLogicoMixin, viewsets.ModelViewSet):
    """CRUD del catálogo de métodos de pago admitidos (RF102).

    Cualquiera puede consultarlo (lo necesita ``usuario_final`` para elegir
    un método al cargar su propio medio de pago); administrarlo (crear,
    editar, desactivar/reactivar) requiere rol ``administrador``.

    Filtros: ``?estado=`` (true/false), ``?tipo=``.
    """

    queryset = MetodoPago.objects.all().order_by('nombre')
    serializer_class = MetodoPagoSerializer
    permission_classes = [SoloAdministradorEscribe]
    FILTROS = ('estado', 'tipo')

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


class MedioPagoClienteViewSet(_BorradoLogicoMixin, viewsets.ModelViewSet):
    """CRUD de los medios de pago de un cliente (RF17).

    ``administrador``/``analista`` ven y gestionan los de cualquier cliente.
    Cualquier otro usuario autenticado (``usuario_final``) solo ve y gestiona
    los del cliente activo de su propia sesión (RF43): al crear uno, el
    ``cliente`` se fuerza al activo (se ignora cualquier otro que mande), y
    el listado/detalle quedan acotados a ese mismo cliente.

    ``/api/transacciones/medios-pago-cliente/``. Filtros: ``?cliente=``,
    ``?metodo_pago=``, ``?estado=`` (true/false). El DELETE hace borrado lógico.
    """

    queryset = MedioPagoCliente.objects.select_related(
        'cliente', 'metodo_pago'
    ).all()
    serializer_class = MedioPagoClienteSerializer
    permission_classes = [IsAuthenticated]
    FILTROS = ('cliente', 'metodo_pago', 'estado')

    def _puede_ver_todos(self):
        return tiene_rol(self.request.user, (ADMINISTRADOR, ANALISTA))

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self._puede_ver_todos():
            cliente_activo = sesion.get_cliente_activo(self.request)
            queryset = (
                queryset.filter(cliente=cliente_activo)
                if cliente_activo is not None
                else queryset.none()
            )
        for campo in self.FILTROS:
            valor = self.request.query_params.get(campo)
            if valor in (None, ''):
                continue
            if campo == 'estado':
                valor = valor.lower() in ('1', 'true', 'si', 'sí')
            queryset = queryset.filter(**{campo: valor})
        return queryset

    def perform_create(self, serializer):
        if self._puede_ver_todos():
            serializer.save()
            return
        cliente_activo = sesion.get_cliente_activo(self.request)
        if cliente_activo is None:
            raise PermissionDenied('No tenés un cliente activo asociado.')
        serializer.save(cliente=cliente_activo)
