import csv
import io

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import HttpResponse
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

from .models import MedioPagoCliente, MetodoPago, Transaccion
from .serializers import MedioPagoClienteSerializer, MetodoPagoSerializer,TransaccionSerializer


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



class TransaccionViewSet(viewsets.ReadOnlyModelViewSet):
    """Historial de transacciones, de solo consulta (RF111 / E4-104 y E4-36).
        ``administrador``/``analista`` ven el historial de cualquier cliente.
        El resto (``usuario_final``) solo ve las del cliente activo de su
        propia sesión, igual criterio que ``MedioPagoClienteViewSet``.
        Filtros disponibles en el listado y en la exportación:
        ``?fecha_desde=``, ``?fecha_hasta=`` (YYYY-MM-DD), ``?tipo=``
        (COMPRA/VENTA), ``?moneda=`` (id), ``?estado=``.

        Exportación: ``GET .../exportar/?formato=csv|excel|pdf``, respetando
        siempre los mismos filtros aplicados en el listado (E4-36).
        """
    queryset = Transaccion.objects.select_related('cliente', 'moneda', 'metodo_pago').all()
    serializer_class = TransaccionSerializer
    permission_classes = [IsAuthenticated]

    def _puede_ver_todos(self):
        return tiene_rol(self.request.user, (ADMINISTRADOR, ANALISTA))

    def _queryset_filtrado(self):
        """Aplica el alcance por cliente activo y los filtros de la query string.

               Centralizado acá para que el listado (``get_queryset``) y la
               exportación (``exportar``) usen siempre exactamente los mismos
               criterios, tal como pide el RF36 (el archivo debe coincidir con
               los filtros aplicados en pantalla).
               """
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
            queryset = queryset.filter(moneda_id=params['moneda'])
        if params.get('estado'):
            queryset = queryset.filter(estado=params['estado'])
        return queryset

    def get_queryset(self):
        return self._queryset_filtrado()

    @action(detail=False, methods=['get'])
    def exportar(self, request):
        formato = request.query_params.get('formato', 'csv').lower()
        transacciones = self._queryset_filtrado()

        columnas = ['ID', 'Fecha', 'Tipo', 'Cliente', 'Moneda', 'Cantidad', 'Tasa', 'Monto total', 'Estado']
        filas = [
            [
                t.id, t.fecha_hora.strftime('%Y-%m-%d %H:%M'), t.get_tipo_display(),
                t.cliente.nombre, t.moneda.codigo, t.cantidad, t.tasa_cambio,
                t.monto_total, t.get_estado_display(),
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

from apps.divisas.models import Moneda
@login_required
def historial_transacciones_view(request):
    """Pantalla propia de "Historial de Transacciones" (RF111 / E4-104),
    en vez de la API navegable de DRF. Mismo criterio de alcance que
    ``TransaccionViewSet``: administrador/analista ven el historial de
    cualquier cliente; el resto (``usuario_final``) solo ve las del
    cliente activo de su propia sesión.

    Los botones de descarga (E4-36) apuntan directo al endpoint
    ``exportar`` de la API, reenviando los mismos filtros aplicados acá
    como query params, para garantizar que el archivo coincida siempre
    con lo que se ve en pantalla.
    """
    ve_todos = tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
    cliente_activo = sesion.get_cliente_activo(request)

    transacciones = Transaccion.objects.select_related(
        'cliente', 'moneda', 'metodo_pago'
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
        transacciones = transacciones.filter(moneda_id=moneda_id)
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