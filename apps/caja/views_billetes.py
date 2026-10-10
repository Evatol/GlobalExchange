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
from .models import Arqueo, Billete, Caja
from .serializers_billetes import (
    AbrirCajaSerializer,
    ArqueoEntradaSerializer,
    ArqueoSerializer,
    BilleteSerializer,
    CajaSerializer,
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


class PrevisualizarOperacionAPIView(APIView):
    """Calcula una operación presencial sin guardarla: montos, comisión y el
    neto de billetes que la caja debe recibir (positivo) o entregar (negativo)
    por moneda.

    Body: ``documento``, ``tipo`` (COMPRA/VENTA/CAMBIO), ``moneda_codigo``,
    ``cantidad`` y, en un cambio, ``moneda_destino_codigo``.
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
        return Response({
            'cliente': cliente.nombre,
            **_desglose(transaccion),
            'neto_esperado': esperado,
        })


class OperarPresencialAPIView(APIView):
    """Registra y confirma una operación presencial en efectivo (RF106).

    Body: los de la previsualización más ``recibidos`` y ``entregados``
    (``{"<billete_id>": cantidad}``). Todo o nada: si algo no cierra, no queda
    nada guardado.
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
                recibidos=d['recibidos'],
                entregados=d['entregados'],
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