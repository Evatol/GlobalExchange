import csv
import io
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.divisas.models import Moneda, TasaCambio
from apps.usuarios import sesion
from apps.usuarios.models import Cliente
from apps.usuarios.permissions import (
    ADMINISTRADOR,
    ANALISTA,
    SoloAdministradorEscribe,
    tiene_rol,
)

from .models import MedioPagoCliente, MetodoPago, Transaccion
from .serializers import MedioPagoClienteSerializer, MetodoPagoSerializer, TransaccionSerializer


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

    def _datos_con_cliente(self, cliente_id):
        datos = self.request.data.copy()
        datos['cliente'] = cliente_id
        return datos

    def create(self, request, *args, **kwargs):
        """El cliente de un ``usuario_final`` se fuerza al activo *antes* de
        validar: la validación comprueba que la cuenta del banco sea de ese
        cliente, y si se forzara después alguien podría asociar la tarjeta
        de otro cliente mandando el id de ese otro cliente."""
        if self._puede_ver_todos():
            return super().create(request, *args, **kwargs)
        cliente_activo = sesion.get_cliente_activo(request)
        if cliente_activo is None:
            raise PermissionDenied('No tenés un cliente activo asociado.')
        serializer = self.get_serializer(data=self._datos_con_cliente(cliente_activo.pk))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Un ``usuario_final`` no puede pasar un medio a otro cliente."""
        if self._puede_ver_todos():
            return super().update(request, *args, **kwargs)
        medio = self.get_object()
        serializer = self.get_serializer(
            medio, data=self._datos_con_cliente(medio.cliente_id),
            partial=kwargs.get('partial', False),
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


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
        'tipo_choices': MetodoPago.TIPO_CHOICES,
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

    context = {
        'usuario': request.user,
        'metodo': metodo,
        'tipo_choices': MetodoPago.TIPO_CHOICES,
        'error': error,
    }
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
        'clientes': Cliente.objects.filter(estado=True).order_by('nombre') if ve_todos else None,
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


TIPOS_OPERACION = ('COMPRA', 'VENTA', 'CAMBIO')


def _preparar_transaccion(cliente, tipo_operacion, moneda_codigo, cantidad, moneda_destino_codigo=None):
    """Arma (sin guardar) una transacción con las tasas vigentes y su
    comisión calculada (E4-144). La comparten la vista previa
    (``CalcularTransaccionAPIView``) y la operación real
    (``_crear_transaccion_digital``), para que siempre den lo mismo.
    """
    if tipo_operacion not in TIPOS_OPERACION:
        return None, 'Tipo de operación inválido (debe ser COMPRA, VENTA o CAMBIO).'

    try:
        cantidad = Decimal(str(cantidad))
        if cantidad <= 0:
            return None, 'La cantidad debe ser mayor a 0.'
    except Exception:
        return None, 'Cantidad no válida.'

    tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)
    if not tasa_obj:
        return None, f'No hay cotización activa para {moneda_codigo}.'

    transaccion = Transaccion(
        cliente=cliente,
        moneda=tasa_obj.moneda,
        tipo=tipo_operacion,
        cantidad=cantidad,
    )
    if tipo_operacion == 'CAMBIO':
        if not moneda_destino_codigo:
            return None, 'Elegí la moneda que querés recibir.'
        if str(moneda_destino_codigo).upper() == str(moneda_codigo).upper():
            return None, 'La moneda que entregás y la que recibís tienen que ser distintas.'
        tasa_destino = TasaCambio.objects.activa_para(moneda_destino_codigo)
        if not tasa_destino:
            return None, f'No hay cotización activa para {moneda_destino_codigo}.'
        transaccion.tasa_cambio = tasa_obj.tasa_para('VENTA')
        transaccion.moneda_destino = tasa_destino.moneda
        transaccion.tasa_cambio_destino = tasa_destino.tasa_para('COMPRA')
    else:
        transaccion.tasa_cambio = tasa_obj.tasa_para(tipo_operacion)

    transaccion.calcular_tasas_y_comisiones()
    return transaccion, None


class CalcularTransaccionAPIView(APIView):
    """Endpoint para E4-144: Lógica de cálculo de tasas y comisiones en la transacción.
    Servicio API REST para simular/desglosar montos en tiempo real, sin persistir nada.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        transaccion, error = _preparar_transaccion(
            sesion.get_cliente_activo(request),
            tipo_operacion=request.data.get('tipo', 'COMPRA').upper(),
            moneda_codigo=request.data.get('moneda_codigo'),
            cantidad=request.data.get('cantidad', '0'),
            moneda_destino_codigo=request.data.get('moneda_destino_codigo'),
        )
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'moneda': transaccion.moneda.codigo,
            'tipo_operacion': transaccion.tipo,
            'cantidad': transaccion.cantidad,
            'tasa_aplicada': transaccion.tasa_cambio,
            'subtotal': transaccion.subtotal,
            'comision_porcentaje': transaccion.comision_porcentaje,
            'monto_comision': transaccion.monto_comision,
            'monto_total': transaccion.monto_total,
            'moneda_destino': transaccion.moneda_destino.codigo if transaccion.moneda_destino else None,
            'tasa_destino': transaccion.tasa_cambio_destino,
            'cantidad_destino': transaccion.cantidad_destino,
        }, status=status.HTTP_200_OK)


def _crear_transaccion_digital(request, tipo_operacion, moneda_codigo, cantidad, medio_pago_id,
                               moneda_destino_codigo=None):
    """Lógica compartida por ``OperarDivisaAPIView`` y ``operar_divisa_view``
    para comprar (E4-19) o vender (E4-20) divisas, o cambiar una por otra.
    """
    cliente_activo = sesion.get_cliente_activo(request)
    if cliente_activo is None:
        return None, 'No tenés un cliente activo asociado a la sesión.'

    usuario_negocio = sesion.usuario_negocio(request)
    if usuario_negocio is None:
        return None, 'No se encontró tu perfil de usuario.'

    transaccion, error = _preparar_transaccion(
        cliente_activo, tipo_operacion, moneda_codigo, cantidad, moneda_destino_codigo,
    )
    if error:
        return None, error

    medio_pago = MedioPagoCliente.objects.select_related('metodo_pago').filter(
        id=medio_pago_id, cliente=cliente_activo, estado=True
    ).first()
    if not medio_pago:
        return None, 'El medio de pago seleccionado no es válido o está inactivo.'
    if tipo_operacion == 'VENTA' and not medio_pago.metodo_pago.permite_venta:
        return None, (
            'Las tarjetas de crédito no se pueden usar para vender divisas: elegí '
            'efectivo, una cuenta o una billetera para recibir el dinero.'
        )
    if tipo_operacion == 'CAMBIO' and medio_pago.metodo_pago.usa_banco:
        return None, (
            'El cambio entre divisas solo se puede hacer en efectivo: las cuentas '
            'del banco son en guaraníes.'
        )

    transaccion.usuario = usuario_negocio
    transaccion.medio_pago = medio_pago
    transaccion.metodo_pago = medio_pago.metodo_pago
    transaccion.modalidad = 'DIGITAL'

    error_limite = transaccion.validar_limite_cliente()
    if error_limite:
        return None, error_limite

    transaccion.save()
    return transaccion, None


def _transaccion_del_cliente_activo(request, pk):
    """Transacción ``pk`` del cliente activo de la sesión, o ``Http404``."""
    cliente_activo = sesion.get_cliente_activo(request)
    transaccion = (
        Transaccion.objects.select_related(
            'moneda', 'moneda_destino', 'metodo_pago', 'medio_pago', 'cliente'
        )
        .filter(pk=pk, cliente=cliente_activo)
        .first()
        if cliente_activo is not None else None
    )
    if transaccion is None:
        raise Http404('No existe esa operación para tu cliente activo.')
    return transaccion


class OperarDivisaAPIView(APIView):
    """Endpoint para E4-19 (comprar) y E4-20 (vender) divisas de forma digital,
    o cambiar una por otra. Ejecuta el cálculo de E4-144 y registra la
    transacción ``PENDIENTE`` de pago.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        transaccion, error = _crear_transaccion_digital(
            request,
            tipo_operacion=request.data.get('tipo', 'COMPRA').upper(),
            moneda_codigo=request.data.get('moneda_codigo'),
            cantidad=request.data.get('cantidad', '0'),
            medio_pago_id=request.data.get('medio_pago_id'),
            moneda_destino_codigo=request.data.get('moneda_destino_codigo'),
        )
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'Operación registrada: queda pendiente hasta que se confirme el pago.',
            **_desglose(transaccion),
        }, status=status.HTTP_201_CREATED)


def _desglose(transaccion):
    """Datos de una transacción para las respuestas de la API."""
    return {
        'transaccion_id': transaccion.id,
        'tipo': transaccion.tipo,
        'moneda': transaccion.moneda.codigo,
        'cantidad': transaccion.cantidad,
        'tasa_aplicada': transaccion.tasa_cambio,
        'subtotal': transaccion.subtotal,
        'comision_porcentaje': transaccion.comision_porcentaje,
        'monto_comision': transaccion.monto_comision,
        'monto_total': transaccion.monto_total,
        'moneda_destino': transaccion.moneda_destino.codigo if transaccion.moneda_destino else None,
        'tasa_destino': transaccion.tasa_cambio_destino,
        'cantidad_destino': transaccion.cantidad_destino,
        'medio_pago': transaccion.medio_pago.alias if transaccion.medio_pago else None,
        'estado': transaccion.estado,
        'observacion': transaccion.observacion,
    }


@login_required
def operar_divisa_view(request):
    """Vista HTML para iniciar una compra (E4-19) o venta (E4-20) de divisas,
    o un cambio entre divisas.
    """
    cliente_activo = sesion.get_cliente_activo(request)
    error = None

    if request.method == 'POST':
        transaccion, error = _crear_transaccion_digital(
            request,
            tipo_operacion=request.POST.get('tipo', 'COMPRA').upper(),
            moneda_codigo=request.POST.get('moneda_codigo'),
            cantidad=request.POST.get('cantidad'),
            medio_pago_id=request.POST.get('medio_pago_id'),
            moneda_destino_codigo=request.POST.get('moneda_destino_codigo'),
        )
        if error is None:
            return redirect('operacion_detalle', pk=transaccion.pk)

    context = {
        'usuario': request.user,
        'cliente_activo': cliente_activo,
        'monedas': Moneda.objects.filter(estado=True).order_by('codigo'),
        'tasas': TasaCambio.objects.vigentes(),
        'medios_pago': (
            MedioPagoCliente.objects.select_related('metodo_pago')
            .filter(cliente=cliente_activo, estado=True)
            if cliente_activo else MedioPagoCliente.objects.none()
        ),
        'datos_enviados': request.POST if request.method == 'POST' else {},
        'pendientes': (
            Transaccion.objects.select_related('moneda', 'moneda_destino')
            .filter(cliente=cliente_activo, estado='PENDIENTE').order_by('-fecha_hora')
            if cliente_activo else Transaccion.objects.none()
        ),
        'error': error,
    }
    return render(request, 'transacciones/operar_divisa.html', context)


@login_required
def operacion_detalle_view(request, pk):
    """Resumen de una operación: tasa aplicada, subtotal, comisión y total."""
    transaccion = _transaccion_del_cliente_activo(request, pk)
    return render(request, 'transacciones/operacion_detalle.html', {
        'usuario': request.user,
        'transaccion': transaccion,
    })


@login_required
@require_POST
def operacion_confirmar_view(request, pk):
    """Confirma el pago (E4-28)."""
    transaccion = _transaccion_del_cliente_activo(request, pk)
    try:
        transaccion.confirmar()
        messages.success(
            request,
            f'Pago confirmado. La operación #{transaccion.pk} se realizó con éxito.',
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect('operacion_detalle', pk=transaccion.pk)


@login_required
@require_POST
def operacion_cancelar_view(request, pk):
    """Cancela a pedido del cliente una operación todavía no pagada (RF23)."""
    transaccion = _transaccion_del_cliente_activo(request, pk)
    try:
        transaccion.cancelar()
        messages.info(request, f'Cancelaste la operación #{transaccion.pk}.')
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    return redirect('operacion_detalle', pk=transaccion.pk)


class TransaccionViewSet(viewsets.ReadOnlyModelViewSet):
    """Historial de transacciones, de solo consulta (RF111 / E4-104 y E4-36)."""
    queryset = Transaccion.objects.select_related(
        'cliente', 'moneda', 'moneda_destino', 'metodo_pago', 'medio_pago'
    ).all()
    serializer_class = TransaccionSerializer
    permission_classes = [IsAuthenticated]

    def _puede_ver_todos(self):
        return tiene_rol(self.request.user, (ADMINISTRADOR, ANALISTA))

    def _queryset_filtrado(self):
        queryset = self.queryset.order_by('-fecha_hora')
        if not self._puede_ver_todos():
            cliente_activo = sesion.get_cliente_activo(self.request)
            queryset = (
                queryset.filter(cliente=cliente_activo)
                if cliente_activo is not None
                else queryset.none()
            )
        params = self.request.query_params
        if params.get('fecha_desde'):
            queryset = queryset.filter(fecha_hora__date__gte=params['fecha_desde'])
        if params.get('fecha_hasta'):
            queryset = queryset.filter(fecha_hora__date__lte=params['fecha_hasta'])
        if params.get('tipo'):
            queryset = queryset.filter(tipo=params['tipo'])
        if params.get('moneda'):
            queryset = queryset.filter(
                Q(moneda_id=params['moneda']) | Q(moneda_destino_id=params['moneda'])
            )
        if params.get('estado'):
            queryset = queryset.filter(estado=params['estado'])
        return queryset

    def get_queryset(self):
        return self._queryset_filtrado()

    @action(detail=True, methods=['post'])
    def confirmar(self, request, pk=None):
        transaccion = _transaccion_del_cliente_activo(request, pk)
        try:
            transaccion.confirmar()
        except ValidationError as exc:
            transaccion.refresh_from_db()
            return Response(
                {'detail': exc.messages[0], **_desglose(transaccion)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({'detail': 'Pago confirmado.', **_desglose(transaccion)})

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        transaccion = _transaccion_del_cliente_activo(request, pk)
        try:
            transaccion.cancelar()
        except ValidationError as exc:
            return Response(
                {'detail': exc.messages[0], **_desglose(transaccion)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({'detail': 'Operación cancelada.', **_desglose(transaccion)})

    @action(detail=False, methods=['get'])
    def exportar(self, request):
        formato = request.query_params.get('formato', 'csv').lower()
        transacciones = self._queryset_filtrado()

        columnas = [
            'ID', 'Fecha', 'Tipo', 'Cliente', 'Moneda', 'Cantidad', 'Tasa', 'Monto total (Gs)',
            'Moneda destino', 'Cantidad destino', 'Medio de pago', 'Estado', 'Observación',
        ]
        filas = [
            [
                t.id, t.fecha_hora.strftime('%Y-%m-%d %H:%M'), t.get_tipo_display(),
                t.cliente.nombre, t.moneda.codigo, t.cantidad, t.tasa_cambio,
                t.monto_total,
                t.moneda_destino.codigo if t.moneda_destino else '',
                t.cantidad_destino if t.cantidad_destino is not None else '',
                t.medio_pago.alias if t.medio_pago else t.metodo_pago.nombre,
                t.get_estado_display(), t.observacion,
            ]
            for t in transacciones
        ]

        if formato == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="historial_transacciones.csv"'
            writer = csv.writer(response)
            writer.writerow(columnas)
            writer.writerows(filas)
            return response

        if formato == 'excel':
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = 'Historial'
            ws.append(columnas)
            for fila in filas:
                ws.append(fila)
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="historial_transacciones.xlsx"'
            return response

        if formato == 'pdf':
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
            tabla = Table([columnas] + [[str(c) for c in fila] for fila in filas])
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E6E9E')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
            ]))
            doc.build([tabla])
            buffer.seek(0)
            response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="historial_transacciones.pdf"'
            return response

        return Response({'detail': 'Formato no soportado. Usá csv, excel o pdf.'}, status=status.HTTP_400_BAD_REQUEST)


@login_required
def historial_transacciones_view(request):
    """Pantalla propia de 'Historial de Transacciones' (RF111 / E4-104)."""
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    cliente_activo = sesion.get_cliente_activo(request)

    transacciones = Transaccion.objects.select_related(
        'cliente', 'moneda', 'moneda_destino', 'metodo_pago', 'medio_pago'
    ).order_by('-fecha_hora')
    if not ve_todos:
        transacciones = (
            transacciones.filter(cliente=cliente_activo)
            if cliente_activo
            else transacciones.none()
        )

    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    tipo = request.GET.get('tipo', '')
    moneda_id = request.GET.get('moneda', '')
    estado = request.GET.get('estado', '')

    if fecha_desde:
        transacciones = transacciones.filter(fecha_hora__date__gte=fecha_desde)
    if fecha_hasta:
        transacciones = transacciones.filter(fecha_hora__date__lte=fecha_hasta)
    if tipo:
        transacciones = transacciones.filter(tipo=tipo)
    if moneda_id:
        transacciones = transacciones.filter(
            Q(moneda_id=moneda_id) | Q(moneda_destino_id=moneda_id)
        )
    if estado:
        transacciones = transacciones.filter(estado=estado)

    query_filtros = request.GET.urlencode()

    context = {
        'usuario': request.user,
        'transacciones': transacciones,
        'monedas': Moneda.objects.filter(estado=True).order_by('codigo'),
        'tipos': Transaccion.TIPOS,
        'estados': Transaccion.ESTADOS,
        'filtros': {
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'tipo': tipo,
            'moneda': moneda_id,
            'estado': estado,
        },
        'query_filtros': query_filtros,
    }
    return render(request, 'transacciones/historial_transacciones.html', context)