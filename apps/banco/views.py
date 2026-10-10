from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response

from apps.usuarios.models import Cliente
from apps.usuarios.permissions import ADMINISTRADOR, ANALISTA, tiene_rol

from . import services
from .models import CuentaBancaria
from .serializers import CuentaBancariaSerializer, MovimientoBancarioSerializer


def _monto(valor):
    """``Decimal`` positivo a partir de lo que mandó el usuario, o ``None``."""
    try:
        monto = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return monto if monto > 0 else None


def _cargar(cuenta, monto):
    """Carga saldo a una cuenta o billetera, o registra el pago de una
    tarjeta (le devuelve crédito). Lanza ``services.ErrorBancario``."""
    concepto = 'Pago de tarjeta' if cuenta.es_tarjeta else 'Carga de saldo'
    return services.acreditar(cuenta.numero, monto, concepto, referencia='CARGA-ADMIN')


class PermisoBanco(BasePermission):
    """Consulta: administrador o analista. Escritura: solo administrador.

    El ``usuario_final`` no tiene acceso: la casa de cambio no muestra el
    saldo bancario de sus clientes, el banco solo acepta o rechaza el pago.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return tiene_rol(request.user, (ADMINISTRADOR, ANALISTA))
        return tiene_rol(request.user, (ADMINISTRADOR,))


class CuentaBancariaViewSet(viewsets.ModelViewSet):
    """API del banco simulado: ``/api/banco/cuentas/``.

    * ``administrador``: abre cuentas, las edita (entidad, nombre del
      titular, estado), las desactiva y les carga saldo
      (``POST .../cuentas/<id>/cargar/`` con ``{"monto": ...}``).
    * ``analista``: consulta todas.
    * ``usuario_final``: sin acceso (ver ``PermisoBanco``).

    ``GET .../cuentas/<id>/movimientos/`` lista los débitos y créditos.
    No hay endpoints para debitar: eso lo hace el sistema al confirmar el
    pago de una operación (``apps.banco.services``).

    Filtros: ``?tipo=``, ``?titular_documento=``, ``?numero=``, ``?estado=``.
    El DELETE hace borrado lógico.
    """

    serializer_class = CuentaBancariaSerializer
    permission_classes = [PermisoBanco]
    FILTROS = ('tipo', 'titular_documento', 'numero', 'estado')

    def get_queryset(self):
        queryset = CuentaBancaria.objects.all()
        for campo in self.FILTROS:
            valor = self.request.query_params.get(campo)
            if valor in (None, ''):
                continue
            if campo == 'estado':
                valor = valor.lower() in ('1', 'true', 'si', 'sí')
            queryset = queryset.filter(**{campo: valor})
        return queryset

    def destroy(self, request, *args, **kwargs):
        cuenta = self.get_object()
        cuenta.desactivar()
        return Response({'detail': f'{cuenta} desactivada correctamente.'})

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        cuenta = self.get_object()
        cuenta.activar()
        return Response({'detail': f'{cuenta} activada.'})

    @action(detail=True, methods=['post'])
    def cargar(self, request, pk=None):
        cuenta = self.get_object()
        monto = _monto(request.data.get('monto'))
        if monto is None:
            return Response(
                {'detail': 'El monto debe ser un número mayor a cero.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            _cargar(cuenta, monto)
        except services.ErrorBancario as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        cuenta.refresh_from_db()
        return Response(self.get_serializer(cuenta).data)

    @action(detail=True, methods=['get'])
    def movimientos(self, request, pk=None):
        cuenta = self.get_object()
        return Response(
            MovimientoBancarioSerializer(cuenta.movimientos.all(), many=True).data
        )


def _solo_admin_o_analista(request):
    if not tiene_rol(request.user, (ADMINISTRADOR, ANALISTA)):
        raise DjangoPermissionDenied('Esta sección es solo para administrador o analista.')


def _solo_admin(request):
    if not tiene_rol(request.user, (ADMINISTRADOR,)):
        raise DjangoPermissionDenied('Solo un administrador puede modificar cuentas del banco.')


@login_required
def gestion_cuentas_view(request):
    """Pantalla del banco simulado: cuentas con su disponible y alta de
    cuentas nuevas. Consulta: administrador o analista; alta: administrador.

    El titular se elige de la lista de clientes, para que el documento
    coincida exactamente con el del cliente (si no, después no podría
    asociar la cuenta como medio de pago).
    """
    _solo_admin_o_analista(request)
    puede_escribir = tiene_rol(request.user, (ADMINISTRADOR,))

    error = None
    if request.method == 'POST':
        _solo_admin(request)
        datos = request.POST.copy()
        cliente = Cliente.objects.filter(pk=datos.get('cliente') or None).first()
        if cliente is None:
            error = 'Elegí el cliente titular de la cuenta.'
        else:
            datos['titular_documento'] = cliente.documento
            datos['titular_nombre'] = cliente.nombre
            serializer = CuentaBancariaSerializer(data=datos)
            if serializer.is_valid():
                cuenta = serializer.save()
                messages.success(request, f'Cuenta {cuenta.numero} abierta.')
                return redirect('gestion_cuentas_banco')
            error = ' '.join(
                str(msg) for errores in serializer.errors.values() for msg in errores
            )

    context = {
        'usuario': request.user,
        'cuentas': CuentaBancaria.objects.all(),
        'clientes': Cliente.objects.filter(estado=True).order_by('nombre'),
        'tipo_choices': CuentaBancaria.TIPO_CHOICES,
        'puede_escribir': puede_escribir,
        'error': error,
    }
    return render(request, 'banco/gestion_cuentas.html', context)


@login_required
def cuenta_detalle_view(request, pk):
    """Movimientos de una cuenta (débitos por compras, créditos por ventas
    y cargas de saldo), con el saldo que quedó después de cada uno."""
    _solo_admin_o_analista(request)
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    return render(request, 'banco/cuenta_detalle.html', {
        'usuario': request.user,
        'cuenta': cuenta,
        'movimientos': cuenta.movimientos.all(),
        'puede_escribir': tiene_rol(request.user, (ADMINISTRADOR,)),
    })


@login_required
@require_POST
def cuenta_cargar_view(request, pk):
    """Carga saldo a una cuenta/billetera o registra el pago de una tarjeta."""
    _solo_admin(request)
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    monto = _monto(request.POST.get('monto'))
    if monto is None:
        messages.error(request, 'El monto debe ser un número mayor a cero.')
    else:
        try:
            _cargar(cuenta, monto)
            messages.success(
                request,
                f'Se acreditaron {services.formatear_guaranies(monto)} en {cuenta.numero}.',
            )
        except services.ErrorBancario as exc:
            messages.error(request, str(exc))
    if request.POST.get('volver') == 'detalle':
        return redirect('cuenta_banco_detalle', pk=cuenta.pk)
    return redirect('gestion_cuentas_banco')


@login_required
@require_POST
def cuenta_toggle_view(request, pk):
    """Activa/desactiva una cuenta del banco."""
    _solo_admin(request)
    cuenta = get_object_or_404(CuentaBancaria, pk=pk)
    cuenta.activar() if not cuenta.estado else cuenta.desactivar()
    return redirect('gestion_cuentas_banco')
