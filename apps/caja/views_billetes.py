"""apps/caja/views_billetes.py - API de RF106 (inventario y arqueo de billetes).

Todo cuelga de /api/caja/, que es lo único que ``CajeroSoloCajaMiddleware``
le deja al rol cajero.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.usuarios import sesion
from apps.usuarios.models import Cliente
from apps.usuarios.permissions import (
    ADMINISTRADOR,
    AdministradorOCajero,
    SoloAdministrador,
    SoloCajero,
    tiene_rol,
)

from . import services
from .models import Arqueo, Billete, Caja, CierreCaja, MovimientoBillete
from .serializers_billetes import (
    AbrirCajaSerializer,
    ArqueoEntradaSerializer,
    ArqueoSerializer,
    BilleteSerializer,
    CajaSerializer,
    CerrarCajaSerializer,
    CierreCajaSerializer,
    MovimientoBilleteSerializer,
    OperacionPresencialSerializer,
    OperacionPreviewSerializer,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _errores(exc):
    """ValidationError de Django -> cuerpo de respuesta 400."""
    if hasattr(exc, 'message_dict'):
        return exc.message_dict
    return {'detail': ' '.join(exc.messages)}


def _usuario_actual(request):
    """``Usuario`` de negocio de quien hace el request (no el ``User`` de login)."""
    usuario = sesion.usuario_negocio(request)
    if usuario is None:
        raise PermissionDenied('No se encontró tu perfil de usuario.')
    return usuario


def _cliente_por_documento(documento):
    cliente = Cliente.objects.filter(documento=str(documento).strip()).first()
    if cliente is None:
        raise DjangoValidationError('No existe un cliente con ese documento.')
    return cliente


def _desglose(t):
    """Datos de una transacción (guardada o solo calculada) para la respuesta."""
    return {
        'transaccion_id': t.pk,
        'tipo': t.tipo,
        'moneda': t.moneda.codigo,
        'cantidad': t.cantidad,
        'tasa_aplicada': t.tasa_cambio,
        'subtotal': t.subtotal,
        'comision_porcentaje': t.comision_porcentaje,
        'monto_comision': t.monto_comision,
        'monto_total': t.monto_total,
        'moneda_destino': t.moneda_destino.codigo if t.moneda_destino else None,
        'tasa_destino': t.tasa_cambio_destino,
        'cantidad_destino': t.cantidad_destino,
        'estado': t.estado,
        'modalidad': t.modalidad,
    }


def _filtrar(queryset, params, campos):
    """Aplica filtros simples de querystring; ``estado`` se lee como booleano."""
    for campo in campos:
        valor = params.get(campo)
        if valor in (None, ''):
            continue
        if campo == 'estado':
            valor = valor.lower() in ('1', 'true', 'si', 'sí')
        queryset = queryset.filter(**{campo: valor})
    return queryset


# ---------------------------------------------------------------------------
# Administrador: denominaciones y cajas
# ---------------------------------------------------------------------------

class BilleteViewSet(viewsets.ModelViewSet):
    """Denominaciones por moneda (RF106), solo administrador. DELETE
    desactiva (borrado lógico); ``POST .../activar/`` reactiva.
    Filtros: ``?moneda=`` (id), ``?estado=`` (true/false)."""

    queryset = Billete.objects.select_related('moneda')
    serializer_class = BilleteSerializer
    permission_classes = [SoloAdministrador]

    def get_queryset(self):
        return _filtrar(super().get_queryset(), self.request.query_params, ('moneda', 'estado'))

    def destroy(self, request, *args, **kwargs):
        billete = self.get_object()
        billete.desactivar()
        return Response({'detail': f'{billete} desactivado correctamente.'})

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        billete = self.get_object()
        billete.activar()
        return Response({'detail': f'{billete} activado.'})


class CajaViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Cajas de las sucursales con su cajero responsable, solo administrador.
    Sin DELETE (una caja tiene historial). Filtros: ``?sucursal=``, ``?estado=``
    (ABIERTA/CERRADA).

    * ``POST .../cajas/<id>/abrir/``  -> ``{"carga_inicial": {"<billete_id>": n}}``
    * ``GET  .../cajas/<id>/inventario/`` -> inventario de esa caja por moneda.
    * ``GET  .../cajas/<id>/balance/`` -> balance de la sesión (E4-100).
    * ``POST .../cajas/<id>/cerrar/`` -> cierra la caja; ``{"contados": {...}}``
      opcional (ver ``CerrarCajaSerializer``).
    """

    queryset = Caja.objects.select_related('sucursal', 'cajero').order_by('sucursal__nombre', 'id')
    serializer_class = CajaSerializer
    permission_classes = [SoloAdministrador]

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get('sucursal'):
            queryset = queryset.filter(sucursal_id=params['sucursal'])
        if params.get('estado'):
            queryset = queryset.filter(estado=params['estado'].upper())
        return queryset

    @action(detail=True, methods=['post'])
    def abrir(self, request, pk=None):
        caja = self.get_object()
        entrada = AbrirCajaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            caja = services.abrir_caja(
                caja, _usuario_actual(request), entrada.validated_data['carga_inicial']
            )
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(caja).data)

    @action(detail=True, methods=['get'])
    def inventario(self, request, pk=None):
        caja = self.get_object()
        return Response({'caja': caja.pk, 'monedas': services.inventario_por_moneda(caja)})

    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        return Response(services.balance_caja(self.get_object()))

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        caja = self.get_object()
        entrada = CerrarCajaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            cierre = services.cerrar_caja(
                caja, _usuario_actual(request), entrada.validated_data['contados']
            )
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(CierreCajaSerializer(cierre).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Cajero: inventario propio y operación presencial
# ---------------------------------------------------------------------------

class MiInventarioAPIView(APIView):
    """Inventario de billetes de la caja abierta del cajero, por moneda y
    denominación, con subtotales y total (RF106)."""

    permission_classes = [SoloCajero]

    def get(self, request):
        try:
            caja = services.caja_abierta_de(_usuario_actual(request))
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response({'caja': caja.pk, 'monedas': services.inventario_por_moneda(caja)})


class MiBalanceAPIView(APIView):
    """Balance de la sesión de la caja abierta del cajero (E4-100): por
    moneda, con cuánto abrió, qué recibió y entregó, y el saldo actual."""

    permission_classes = [SoloCajero]

    def get(self, request):
        try:
            caja = services.caja_abierta_de(_usuario_actual(request))
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(services.balance_caja(caja))


class MiCierreAPIView(APIView):
    """``POST``: el cajero cierra su caja (E4-100). Body opcional:
    ``{"contados": {"<moneda_id>": {"<billete_id>": cantidad}}}``; las monedas
    que se incluyen se cuentan y dejan un arqueo con su diferencia."""

    permission_classes = [SoloCajero]

    def post(self, request):
        entrada = CerrarCajaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario = _usuario_actual(request)
        try:
            caja = services.caja_abierta_de(usuario)
            cierre = services.cerrar_caja(caja, usuario, entrada.validated_data['contados'])
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(CierreCajaSerializer(cierre).data, status=status.HTTP_201_CREATED)


class PrevisualizarOperacionAPIView(APIView):
    """Calcula una operación presencial sin guardarla: montos, comisión y el
    neto de billetes que la caja debe recibir (positivo) o entregar (negativo)
    por moneda.

    Body: ``documento``, ``tipo`` (COMPRA/VENTA/CAMBIO), ``moneda_codigo``,
    ``cantidad`` y, en un cambio, ``moneda_destino_codigo``.

    Si el cajero tiene una caja abierta, también devuelve ``billetes``: los que
    el sistema registraría solo para esa operación (E4-101).
    """

    permission_classes = [SoloCajero]

    def post(self, request):
        entrada = OperacionPreviewSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        try:
            cliente = _cliente_por_documento(d['documento'])
            transaccion, esperado = services.previsualizar_operacion_presencial(
                cliente=cliente,
                tipo=d['tipo'],
                moneda_codigo=d['moneda_codigo'],
                cantidad=d['cantidad'],
                moneda_destino_codigo=d.get('moneda_destino_codigo') or None,
            )
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        caja = Caja.objects.filter(cajero=_usuario_actual(request), estado='ABIERTA').first()
        return Response({
            'cliente': cliente.nombre,
            **_desglose(transaccion),
            'neto_esperado': esperado,
            'billetes': services.sugerir_billetes(caja, transaccion) if caja else None,
        })


class OperarPresencialAPIView(APIView):
    """Registra y confirma una operación presencial en efectivo (RF106).

    Body: los de la previsualización y, opcionalmente, ``recibidos`` y
    ``entregados`` (``{"<billete_id>": cantidad}``). Sin ellos, el sistema arma
    solo el desglose en billetes y registra los movimientos (E4-101); con
    ellos, respeta lo que cargó el cajero. Todo o nada: si algo no cierra, no
    queda nada guardado.
    """

    permission_classes = [SoloCajero]

    def post(self, request):
        entrada = OperacionPresencialSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        usuario = _usuario_actual(request)
        try:
            caja = services.caja_abierta_de(usuario)
            cliente = _cliente_por_documento(d['documento'])
            transaccion = services.registrar_operacion_presencial(
                caja=caja,
                usuario=usuario,
                cliente=cliente,
                tipo=d['tipo'],
                moneda_codigo=d['moneda_codigo'],
                cantidad=d['cantidad'],
                recibidos=d.get('recibidos'),
                entregados=d.get('entregados'),
                moneda_destino_codigo=d.get('moneda_destino_codigo') or None,
            )
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {'detail': 'Operación registrada y confirmada.', **_desglose(transaccion)},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Arqueo
# ---------------------------------------------------------------------------

class ArqueoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Arqueos de caja (RF106).

    * ``POST``: solo el cajero, sobre su caja abierta. Body: ``moneda`` (id) y
      ``contados`` (``{"<billete_id>": cantidad}``). Registra lo contado y la
      diferencia contra lo esperado; no modifica el stock.
    * ``GET``: el administrador ve todos; el cajero, solo los suyos.
      Filtros: ``?caja=``, ``?moneda=``.
    """

    queryset = Arqueo.objects.select_related('caja', 'cajero', 'moneda').prefetch_related(
        'detalles__billete'
    )
    serializer_class = ArqueoSerializer

    def get_permissions(self):
        if self.action == 'create':
            return [SoloCajero()]
        return [AdministradorOCajero()]

    def get_serializer_class(self):
        return ArqueoEntradaSerializer if self.action == 'create' else ArqueoSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if not tiene_rol(self.request.user, (ADMINISTRADOR,)):
            usuario = sesion.usuario_negocio(self.request)
            queryset = queryset.filter(cajero=usuario) if usuario else queryset.none()
        params = self.request.query_params
        if params.get('caja'):
            queryset = queryset.filter(caja_id=params['caja'])
        if params.get('moneda'):
            queryset = queryset.filter(moneda_id=params['moneda'])
        return queryset

    def create(self, request, *args, **kwargs):
        entrada = ArqueoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario = _usuario_actual(request)
        try:
            caja = services.caja_abierta_de(usuario)
            arqueo = services.registrar_arqueo(
                caja, usuario,
                entrada.validated_data['moneda'],
                entrada.validated_data['contados'],
            )
        except DjangoValidationError as exc:
            return Response(_errores(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(ArqueoSerializer(arqueo).data, status=status.HTTP_201_CREATED)

# ---------------------------------------------------------------------------
# Movimientos de billetes y cierres: consulta
# ---------------------------------------------------------------------------

class _SoloLecturaDeSuCajaMixin:
    """El administrador ve todo; el cajero, solo lo de sus cajas."""

    permission_classes = [AdministradorOCajero]

    def _acotar_al_cajero(self, queryset):
        if tiene_rol(self.request.user, (ADMINISTRADOR,)):
            return queryset
        usuario = sesion.usuario_negocio(self.request)
        return queryset.filter(caja__cajero=usuario) if usuario else queryset.none()


class MovimientoBilleteViewSet(
    _SoloLecturaDeSuCajaMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Movimientos de billetes registrados automáticamente al confirmar una
    operación presencial, y la carga inicial de la apertura (E4-101). Solo
    lectura: los movimientos los crea ``services.registrar_movimientos_billetes``.

    Filtros: ``?caja=``, ``?tipo=`` (ENTRADA/SALIDA), ``?transaccion=``,
    ``?moneda=`` (id), ``?fecha_desde=`` y ``?fecha_hasta=`` (YYYY-MM-DD).
    """

    queryset = MovimientoBillete.objects.select_related(
        'caja', 'billete__moneda', 'usuario', 'transaccion'
    ).order_by('-fecha_hora', '-id')
    serializer_class = MovimientoBilleteSerializer

    def get_queryset(self):
        queryset = self._acotar_al_cajero(super().get_queryset())
        p = self.request.query_params
        if p.get('caja'):
            queryset = queryset.filter(caja_id=p['caja'])
        if p.get('tipo'):
            queryset = queryset.filter(tipo=p['tipo'].upper())
        if p.get('transaccion'):
            queryset = queryset.filter(transaccion_id=p['transaccion'])
        if p.get('moneda'):
            queryset = queryset.filter(billete__moneda_id=p['moneda'])
        if p.get('fecha_desde'):
            queryset = queryset.filter(fecha_hora__date__gte=p['fecha_desde'])
        if p.get('fecha_hasta'):
            queryset = queryset.filter(fecha_hora__date__lte=p['fecha_hasta'])
        return queryset


class CierreCajaViewSet(
    _SoloLecturaDeSuCajaMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Historial de cierres de caja (E4-100), con el balance de cada sesión.
    Solo lectura; los cierres se crean con ``POST .../cajas/<id>/cerrar/``
    (administrador) o ``POST .../mi-cierre/`` (cajero). Filtro: ``?caja=``."""

    queryset = CierreCaja.objects.select_related('caja', 'cerrado_por').prefetch_related(
        'detalles__moneda'
    )
    serializer_class = CierreCajaSerializer

    def get_queryset(self):
        queryset = self._acotar_al_cajero(super().get_queryset())
        if self.request.query_params.get('caja'):
            queryset = queryset.filter(caja_id=self.request.query_params['caja'])
        return queryset
