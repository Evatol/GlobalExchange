from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.shortcuts import redirect, render
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


@login_required
def gestion_metodos_pago_view(request):
    """Pantalla propia para el catálogo de métodos de pago (RF102), en vez
    de la API navegable de DRF. Reutiliza ``MetodoPagoSerializer``. Solo
    administrador."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise DjangoPermissionDenied('Esta sección es solo para administradores.')

    error = None
    if request.method == 'POST':
        serializer = MetodoPagoSerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_metodos_pago')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    context = {
        'usuario': request.user,
        'metodos': MetodoPago.objects.all().order_by('nombre'),
        'error': error,
    }
    return render(request, 'transacciones/gestion_metodos_pago.html', context)


@login_required
def metodo_pago_editar_view(request, pk):
    """Edita el nombre/tipo de un método de pago del catálogo. Reutiliza
    ``MetodoPagoSerializer``. Solo administrador."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise DjangoPermissionDenied('Esta sección es solo para administradores.')
    metodo = MetodoPago.objects.filter(pk=pk).first()
    if metodo is None:
        return redirect('gestion_metodos_pago')

    error = None
    if request.method == 'POST':
        serializer = MetodoPagoSerializer(instance=metodo, data=request.POST, partial=True)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_metodos_pago')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    context = {'usuario': request.user, 'metodo': metodo, 'error': error}
    return render(request, 'transacciones/metodo_pago_editar.html', context)


@login_required
def metodo_pago_toggle_view(request, pk):
    """Activa/desactiva un método de pago del catálogo."""
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise DjangoPermissionDenied('Esta sección es solo para administradores.')
    metodo = MetodoPago.objects.filter(pk=pk).first()
    if metodo is not None:
        metodo.activar() if not metodo.estado else metodo.desactivar()
    return redirect('gestion_metodos_pago')


@login_required
def gestion_medios_pago_view(request):
    """Pantalla propia de "Mis Medios de Pago" (RF17), en vez de la API
    navegable de DRF. Mismo criterio de alcance que ``MedioPagoClienteViewSet``:
    administrador/analista ven y gestionan los de cualquier cliente; el resto
    de los usuarios (``usuario_final``) solo los del cliente activo de su
    propia sesión (RF43), y el ``cliente`` del alta se fuerza siempre al
    activo. Reutiliza ``MedioPagoClienteSerializer`` para no duplicar
    validaciones (identificador duplicado, método de pago desactivado, etc.).
    """
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    cliente_activo = sesion.get_cliente_activo(request)

    error = None
    if request.method == 'POST':
        datos = request.POST.copy()
        if not ve_todos:
            if cliente_activo is None:
                raise DjangoPermissionDenied('No tenés un cliente activo asociado.')
            datos['cliente'] = cliente_activo.pk
        serializer = MedioPagoClienteSerializer(data=datos)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_medios_pago')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    medios = MedioPagoCliente.objects.select_related('cliente', 'metodo_pago').all()
    if not ve_todos:
        medios = medios.filter(cliente=cliente_activo) if cliente_activo else medios.none()

    context = {
        'usuario': request.user,
        'medios': medios,
        'metodos': MetodoPago.objects.filter(estado=True).order_by('nombre'),
        'clientes': sesion.clientes_disponibles(request) if not ve_todos else None,
        've_todos': ve_todos,
        'cliente_activo': cliente_activo,
        'error': error,
    }
    return render(request, 'transacciones/gestion_medios_pago.html', context)


@login_required
def medio_pago_editar_view(request, pk):
    """Edita un medio de pago existente (alias, identificador, titular,
    método de pago). Respeta el mismo alcance que el listado/alta:
    administrador/analista pueden editar cualquiera; el resto solo los del
    cliente activo de su sesión, y el ``cliente`` se mantiene siempre el
    mismo (no se puede "mover" un medio de pago a otro cliente desde acá).
    Reutiliza ``MedioPagoClienteSerializer``."""
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    medios = MedioPagoCliente.objects.select_related('cliente', 'metodo_pago')
    if not ve_todos:
        cliente_activo = sesion.get_cliente_activo(request)
        medios = medios.filter(cliente=cliente_activo) if cliente_activo else medios.none()

    medio = medios.filter(pk=pk).first()
    if medio is None:
        return redirect('gestion_medios_pago')

    error = None
    if request.method == 'POST':
        datos = request.POST.copy()
        datos['cliente'] = medio.cliente_id  # nunca se reasigna a otro cliente desde acá
        serializer = MedioPagoClienteSerializer(instance=medio, data=datos, partial=True)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_medios_pago')
        error = ' '.join(
            str(msg) for errores in serializer.errors.values() for msg in errores
        )

    context = {
        'usuario': request.user,
        'medio': medio,
        'metodos': MetodoPago.objects.filter(estado=True).order_by('nombre'),
        've_todos': ve_todos,
        'error': error,
    }
    return render(request, 'transacciones/medio_pago_editar.html', context)


@login_required
def medio_pago_toggle_view(request, pk):
    """Activa/desactiva un medio de pago desde la pantalla de gestión,
    respetando el mismo alcance que la vista de listado/alta."""
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    medios = MedioPagoCliente.objects.all()
    if not ve_todos:
        cliente_activo = sesion.get_cliente_activo(request)
        medios = medios.filter(cliente=cliente_activo) if cliente_activo else medios.none()

    medio = medios.filter(pk=pk).first()
    if medio is not None:
        medio.activar() if not medio.estado else medio.desactivar()
    return redirect('gestion_medios_pago')
