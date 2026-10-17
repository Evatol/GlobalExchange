from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.usuarios.models import Usuario
from apps.usuarios.permissions import (
    ADMINISTRADOR,
    CAJERO,
    SoloAdministrador,
    tiene_rol,
)

from . import services
from .models import AsignacionCajero, Billete, Sucursal, Terminal
from .serializers import (
    AsignacionCajeroSerializer,
    SucursalSerializer,
    TerminalSerializer,
)


class SucursalViewSet(viewsets.ModelViewSet):
    """CRUD de sucursales presenciales (RF105 / E4-98).

    Solo el rol ``administrador`` puede consultar y administrar. El DELETE
    hace borrado lógico, porque ``Caja`` depende de ``Sucursal`` con
    ``on_delete=CASCADE`` y un borrado real eliminaría sus cajas.
    ``POST .../activar/`` reactiva una sucursal desactivada.
    """

    queryset = Sucursal.objects.all().order_by('nombre')
    serializer_class = SucursalSerializer
    permission_classes = [SoloAdministrador]

    def destroy(self, request, *args, **kwargs):
        sucursal = self.get_object()
        sucursal.desactivar()
        return Response(
            {'detail': f'Sucursal {sucursal.nombre} desactivada correctamente.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        sucursal = self.get_object()
        sucursal.activar()
        return Response({'detail': f'Sucursal {sucursal.nombre} activada.'})


class TerminalViewSet(viewsets.ModelViewSet):
    """Administración de terminales y comprobación pública de disponibilidad."""

    queryset = Terminal.objects.select_related('sucursal', 'caja').order_by('nombre')
    serializer_class = TerminalSerializer
    permission_classes = [SoloAdministrador]

    def destroy(self, request, *args, **kwargs):
        terminal = self.get_object()
        terminal.estado = Terminal.INACTIVA
        terminal.save(update_fields=['estado'])
        return Response({
            'detail': f'Terminal {terminal.nombre} desactivada correctamente.'
        })

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        terminal = self.get_object()
        serializer = self.get_serializer(
            terminal, data={'estado': Terminal.ACTIVA}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': f'Terminal {terminal.nombre} activada.'})

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[AllowAny],
        url_path='iniciar-operacion',
    )
    def iniciar_operacion(self, request, pk=None):
        terminal = self.get_object()
        try:
            services.validar_terminal_operativa(terminal)
        except DjangoValidationError as exc:
            return Response(
                {'detail': _errores_validacion(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            'operativa': True,
            'terminal': terminal.nombre,
            'sucursal': terminal.sucursal.nombre,
            'mensaje': 'Terminal operativa. Puede iniciar una operación.',
        })


class AsignacionCajeroViewSet(viewsets.ModelViewSet):
    """Asignación de cajeros a sucursales (RF105 / E4-98), solo administrador.

    Un tercer cajero en la misma sucursal, o un usuario sin rol cajero, se
    rechaza con 400 y un mensaje claro. DELETE desasigna (borrado lógico) y
    ``POST .../activar/`` reasigna, volviendo a validar el máximo.
    Filtro: ``?sucursal=`` (id).
    """

    queryset = AsignacionCajero.objects.select_related('sucursal', 'usuario').order_by(
        'sucursal__nombre', 'usuario__username'
    )
    serializer_class = AsignacionCajeroSerializer
    permission_classes = [SoloAdministrador]

    def get_queryset(self):
        queryset = super().get_queryset()
        sucursal = self.request.query_params.get('sucursal')
        if sucursal:
            queryset = queryset.filter(sucursal_id=sucursal)
        return queryset

    def destroy(self, request, *args, **kwargs):
        asignacion = self.get_object()
        asignacion.desactivar()
        return Response(
            {'detail': f'{asignacion} desasignado correctamente.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        asignacion = self.get_object()
        try:
            asignacion.activar()
        except DjangoValidationError as exc:
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': f'{asignacion} asignado nuevamente.'})


# ---------------------------------------------------------------------------
# Pantallas propias (HTML) en vez de la API navegable de DRF. Solo administrador.
# ---------------------------------------------------------------------------

def _solo_administrador(request):
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise DjangoPermissionDenied('Esta sección es solo para administradores.')


def _errores(serializer):
    """Une los mensajes de error de un serializer en un solo texto."""
    return ' '.join(
        str(msg) for errores in serializer.errors.values() for msg in errores
    )


def _errores_validacion(exc):
    if hasattr(exc, 'message_dict'):
        return ' '.join(
            str(msg) for errores in exc.message_dict.values() for msg in errores
        )
    return ' '.join(exc.messages)


def _entero(valor):
    """Convierte a int un valor de formulario, o ``None`` si no es un número."""
    return int(valor) if valor and valor.isdigit() else None


def _stock_inicial_form(request):
    stock = {}
    for campo, valor in request.POST.items():
        if not campo.startswith('stock_'):
            continue
        billete_id = _entero(campo[6:])
        cantidad = 0 if valor == '' else _entero(valor)
        if billete_id is None or cantidad is None:
            raise ValueError('Las cantidades de billetes deben ser números enteros.')
        stock[str(billete_id)] = cantidad
    return stock


@login_required
def gestion_terminales_view(request):
    """Alta y consulta administrativa de terminales de autoservicio."""
    _solo_administrador(request)
    error = None
    if request.method == 'POST':
        try:
            data = request.POST.dict()
            data['stock_inicial'] = _stock_inicial_form(request)
            serializer = TerminalSerializer(data=data)
            if serializer.is_valid():
                serializer.save()
                return redirect('gestion_terminales')
            error = _errores(serializer)
        except (DjangoValidationError, ValueError) as exc:
            error = _errores_validacion(exc) if isinstance(
                exc, DjangoValidationError
            ) else str(exc)
        except DRFValidationError as exc:
            error = str(exc.detail)

    context = {
        'usuario': request.user,
        'terminales': Terminal.objects.select_related('sucursal', 'caja').order_by('nombre'),
        'sucursales': Sucursal.objects.filter(estado=True).order_by('nombre'),
        'billetes': Billete.objects.filter(estado=True).select_related('moneda'),
        'estados': Terminal.ESTADOS,
        'error': error,
    }
    return render(request, 'caja/gestion_terminales.html', context)


@login_required
def terminal_editar_view(request, pk):
    """Edita el nombre, la sucursal y el estado operativo de una terminal."""
    _solo_administrador(request)
    terminal = get_object_or_404(Terminal.objects.select_related('sucursal'), pk=pk)
    error = None
    if request.method == 'POST':
        serializer = TerminalSerializer(
            terminal, data=request.POST, partial=True
        )
        if serializer.is_valid():
            try:
                serializer.save()
                return redirect('gestion_terminales')
            except DjangoValidationError as exc:
                error = _errores_validacion(exc)
        else:
            error = _errores(serializer)
    return render(request, 'caja/terminal_editar.html', {
        'usuario': request.user,
        'terminal': terminal,
        'sucursales': Sucursal.objects.filter(estado=True).order_by('nombre'),
        'estados': Terminal.ESTADOS,
        'error': error,
    })


@login_required
@require_POST
def terminal_desactivar_view(request, pk):
    """Da de baja lógica una terminal y conserva su caja e historial."""
    _solo_administrador(request)
    Terminal.objects.filter(pk=pk).update(estado=Terminal.INACTIVA)
    return redirect('gestion_terminales')


@require_http_methods(['GET', 'POST'])
def terminal_demo_view(request, pk):
    """Pantalla pública simulada que valida el estado antes de iniciar."""
    terminal = get_object_or_404(
        Terminal.objects.select_related('sucursal'), pk=pk
    )
    mensaje = None
    error = None
    response_status = status.HTTP_200_OK
    try:
        services.validar_terminal_operativa(terminal)
        if request.method == 'POST':
            mensaje = 'Terminal operativa. La simulación está lista para iniciar una operación.'
    except DjangoValidationError as exc:
        error = _errores_validacion(exc)
        response_status = status.HTTP_409_CONFLICT
    return render(
        request,
        'caja/terminal_demo.html',
        {'terminal': terminal, 'mensaje': mensaje, 'error': error},
        status=response_status,
    )


@login_required
def gestion_sucursales_view(request):
    """Pantalla de sucursales y cajeros (RF105 / E4-98). Reutiliza los
    serializers para no duplicar las reglas (máximo de 2 cajeros por sucursal
    y solo usuarios con rol cajero).

    Las sucursales nuevas nacen activas; para desactivar se usa el botón de la
    tabla. El formulario no manda ``estado`` a propósito: un checkbox sin
    marcar no llega en el POST y el serializer lo tomaría como activo.
    """
    _solo_administrador(request)

    error = None
    if request.method == 'POST':
        if request.POST.get('accion') == 'asignar':
            # Si ese cajero ya estuvo en la sucursal y se lo había quitado, se
            # reactiva la misma fila (hay unicidad por sucursal y usuario) y
            # se vuelven a validar las reglas.
            previa = AsignacionCajero.objects.filter(
                sucursal_id=_entero(request.POST.get('sucursal')),
                usuario_id=_entero(request.POST.get('usuario')),
            ).first()
            if previa is not None:
                serializer = AsignacionCajeroSerializer(
                    instance=previa, data={'estado': True}, partial=True
                )
            else:
                serializer = AsignacionCajeroSerializer(data=request.POST)
        else:
            serializer = SucursalSerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_sucursales')
        error = _errores(serializer)

    sucursales = list(
        Sucursal.objects.prefetch_related('asignaciones_cajero__usuario').order_by('nombre')
    )
    for sucursal in sucursales:
        sucursal.cajeros_activos = [
            a for a in sucursal.asignaciones_cajero.all() if a.estado
        ]

    logins_cajero = get_user_model().objects.filter(
        groups__name=CAJERO
    ).values_list('username', flat=True)
    cajeros = Usuario.objects.filter(
        username__in=list(logins_cajero), estado=True
    ).order_by('username')

    context = {
        'usuario': request.user,
        'sucursales': sucursales,
        'cajeros': cajeros,
        'max_cajeros': AsignacionCajero.MAX_CAJEROS,
        'error': error,
    }
    return render(request, 'caja/gestion_sucursales.html', context)


@login_required
def sucursal_editar_view(request, pk):
    """Edita nombre y dirección de una sucursal."""
    _solo_administrador(request)
    sucursal = Sucursal.objects.filter(pk=pk).first()
    if sucursal is None:
        return redirect('gestion_sucursales')

    error = None
    if request.method == 'POST':
        serializer = SucursalSerializer(instance=sucursal, data=request.POST, partial=True)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_sucursales')
        error = _errores(serializer)

    context = {'usuario': request.user, 'sucursal': sucursal, 'error': error}
    return render(request, 'caja/sucursal_editar.html', context)


@login_required
@require_POST
def sucursal_toggle_view(request, pk):
    """Activa o desactiva una sucursal (borrado lógico)."""
    _solo_administrador(request)
    sucursal = Sucursal.objects.filter(pk=pk).first()
    if sucursal is not None:
        if sucursal.estado:
            sucursal.desactivar()
        else:
            sucursal.activar()
    return redirect('gestion_sucursales')


@login_required
@require_POST
def asignacion_cajero_desasignar_view(request, pk):
    """Quita un cajero de su sucursal (borrado lógico). Para volver a
    asignarlo se usa el formulario de la pantalla, que lo reactiva."""
    _solo_administrador(request)
    asignacion = AsignacionCajero.objects.filter(pk=pk).first()
    if asignacion is not None:
        asignacion.desactivar()
    return redirect('gestion_sucursales')