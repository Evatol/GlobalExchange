from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.shortcuts import redirect, render
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.divisas.models import TasaCambio
from apps.usuarios import sesion
from apps.usuarios.permissions import (
    ADMINISTRADOR,
    ANALISTA,
    SoloAdministradorEscribe,
    tiene_rol,
)

from .models import MedioPagoCliente, MetodoPago, Transaccion
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
    """Pantalla propia para el catálogo de métodos de pago (RF102)."""
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
    """Edita el nombre/tipo de un método de pago del catálogo."""
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
    """Pantalla propia de 'Mis Medios de Pago' (RF17)."""
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
    """Edita un medio de pago existente."""
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
        datos['cliente'] = medio.cliente_id
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
    """Activa/desactiva un medio de pago desde la pantalla de gestión."""
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    medios = MedioPagoCliente.objects.all()
    if not ve_todos:
        cliente_activo = sesion.get_cliente_activo(request)
        medios = medios.filter(cliente=cliente_activo) if cliente_activo else medios.none()

    medio = medios.filter(pk=pk).first()
    if medio is not None:
        medio.activar() if not medio.estado else medio.desactivar()
    return redirect('gestion_medios_pago')



class CalcularTransaccionAPIView(APIView):
    """
    Endpoint para E4-144: Lógica de cálculo de tasas y comisiones en la transacción.
    Servicio API REST para simular/desglosar montos en tiempo real.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        moneda_codigo = request.data.get('moneda_codigo')
        cantidad_str = request.data.get('cantidad', '0')
        tipo_operacion = request.data.get('tipo', 'COMPRA').upper()

        try:
            cantidad = Decimal(str(cantidad_str))
            if cantidad <= 0:
                return Response(
                    {'error': 'La cantidad debe ser mayor a 0.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception:
            return Response(
                {'error': 'Cantidad no válida.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)
        if not tasa_obj:
            return Response(
                {'error': f'No existe una cotización activa para {moneda_codigo}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        tasa_aplicada = tasa_obj.tasa_compra if tipo_operacion == 'COMPRA' else tasa_obj.tasa_venta

        tx_temporal = Transaccion(
            tipo=tipo_operacion,
            cantidad=cantidad,
            tasa_cambio=tasa_aplicada
        )
        desglose = tx_temporal.calcular_tasas_y_comisiones()

        return Response({
            'moneda': moneda_codigo,
            'tipo_operacion': tipo_operacion,
            'cantidad': cantidad,
            'tasa_aplicada': tasa_aplicada,
            'subtotal': desglose['subtotal'],
            'comision_porcentaje': tx_temporal.comision_porcentaje,
            'monto_comision': desglose['comision'],
            'monto_total': desglose['monto_total'],
        }, status=status.HTTP_200_OK)


class ComprarDivisaAPIView(APIView):
    """
    Endpoint para E4-19: Comprar divisas de forma digital.
    Ejecuta el cálculo de E4-144, descuenta/registra y confirma la transacción.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        moneda_codigo = request.data.get('moneda_codigo')
        cantidad_str = request.data.get('cantidad', '0')
        medio_pago_id = request.data.get('medio_pago_id')

        cliente_activo = sesion.get_cliente_activo(request)
        if not cliente_activo:
            return Response(
                {'error': 'No posees un cliente activo asociado a la sesión.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            cantidad = Decimal(str(cantidad_str))
            if cantidad <= 0:
                return Response({'error': 'La cantidad debe ser mayor a 0.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'Monto de cantidad inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)
        if not tasa_obj:
            return Response({'error': f'No hay cotización activa para {moneda_codigo}.'},
                            status=status.HTTP_400_BAD_REQUEST)

        medio_pago = MedioPagoCliente.objects.filter(
            id=medio_pago_id, cliente=cliente_activo, estado=True
        ).first()

        if not medio_pago:
            return Response(
                {'error': 'El medio de pago seleccionado no es válido o está inactivo.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        transaccion = Transaccion(
            usuario=request.user,
            cliente=cliente_activo,
            moneda=tasa_obj.moneda,
            metodo_pago=medio_pago.metodo_pago,
            tipo='COMPRA',
            cantidad=cantidad,
            tasa_cambio=tasa_obj.tasa_compra,
            modalidad='DIGITAL'
        )

        desglose = transaccion.calcular_tasas_y_comisiones()
        transaccion.confirmar()

        return Response({
            'detail': 'Compra realizada con éxito.',
            'transaccion_id': transaccion.id,
            'moneda': tasa_obj.moneda.codigo,
            'cantidad': cantidad,
            'tasa_aplicada': tasa_obj.tasa_compra,
            'subtotal': desglose['subtotal'],
            'comision': desglose['comision'],
            'monto_total': desglose['monto_total'],
            'estado': transaccion.estado
        }, status=status.HTTP_201_CREATED)


@login_required
def operacion_compra_view(request):
    """
    Vista HTML interactiva para comprar divisas desde la interfaz.
    """
    cliente_activo = sesion.get_cliente_activo(request)
    error = None
    exito = None

    if request.method == 'POST':
        moneda_codigo = request.POST.get('moneda_codigo')
        cantidad = request.POST.get('cantidad')
        medio_pago_id = request.POST.get('medio_pago_id')

        tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)
        medio_pago = MedioPagoCliente.objects.filter(id=medio_pago_id, estado=True).first()

        if tasa_obj and medio_pago and cliente_activo:
            tx = Transaccion(
                usuario=request.user,
                cliente=cliente_activo,
                moneda=tasa_obj.moneda,
                metodo_pago=medio_pago.metodo_pago,
                tipo='COMPRA',
                cantidad=Decimal(cantidad),
                tasa_cambio=tasa_obj.tasa_compra,
                modalidad='DIGITAL'
            )
            tx.calcular_tasas_y_comisiones()
            tx.confirmar()
            exito = f"¡Compra realizada exitosamente! ID de Transacción: #{tx.id}"
        else:
            error = "No se pudo procesar la compra. Verifique los datos ingresados."

    context = {
        'usuario': request.user,
        'medios_pago': MedioPagoCliente.objects.filter(cliente=cliente_activo, estado=True) if cliente_activo else [],
        'error': error,
        'exito': exito
    }
    return render(request, 'transacciones/compra_divisas.html', context)