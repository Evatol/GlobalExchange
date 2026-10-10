"""apps/caja/views_pantallas.py - pantallas HTML de RF106 (inventario y arqueo).

Propias del portal, en vez de la API navegable de DRF. Reutilizan los
serializers y los services de ``views_billetes`` para no duplicar reglas.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.divisas.models import Moneda
from apps.usuarios import sesion
from apps.usuarios.permissions import es_cajero

from . import services
from .models import Arqueo, AsignacionCajero, Billete, Caja
from .serializers_billetes import BilleteSerializer, CajaSerializer
from .views import _entero, _errores, _solo_administrador


def _leer_cantidades(post, prefijo):
    """{billete_id: cantidad} desde los campos ``<prefijo><billete_id>`` de un
    formulario. Un campo vacío cuenta como 0; cualquier valor que no sea un
    entero >= 0 lanza ``ValidationError``."""
    cantidades = {}
    for clave, valor in post.items():
        if not clave.startswith(prefijo):
            continue
        id_texto = clave[len(prefijo):]
        valor = valor.strip()
        valido = id_texto.isdigit() and (valor == '' or (valor.isascii() and valor.isdigit()))
        if not valido:
            raise DjangoValidationError(
                'Ingresá solo números enteros (0 o más) en las cantidades.'
            )
        cantidades[int(id_texto)] = int(valor or 0)
    return cantidades


# ---------------------------------------------------------------------------
# Administrador: denominaciones y cajas
# ---------------------------------------------------------------------------

@login_required
def gestion_denominaciones_view(request):
    """Denominaciones de billetes por moneda (RF106), solo administrador.
    Reutiliza ``BilleteSerializer`` (unicidad por moneda y denominación)."""
    _solo_administrador(request)

    error = None
    if request.method == 'POST':
        serializer = BilleteSerializer(data=request.POST)
        if serializer.is_valid():
            serializer.save()
            return redirect('gestion_denominaciones')
        error = _errores(serializer)

    context = {
        'usuario': request.user,
        'billetes': Billete.objects.select_related('moneda'),
        'monedas': Moneda.objects.filter(estado=True).order_by('codigo'),
        'error': error,
    }
    return render(request, 'caja/gestion_denominaciones.html', context)


@login_required
@require_POST
def billete_toggle_view(request, pk):
    """Activa o desactiva una denominación (borrado lógico)."""
    _solo_administrador(request)
    billete = Billete.objects.filter(pk=pk).first()
    if billete is not None:
        if billete.estado:
            billete.desactivar()
        else:
            billete.activar()
    return redirect('gestion_denominaciones')


@login_required
def gestion_cajas_view(request):
    """Cajas de las sucursales con su cajero responsable (RF106), solo
    administrador. La caja se crea a partir de una asignación activa de
    cajero (E4-98), así sucursal y cajero siempre son coherentes."""
    _solo_administrador(request)

    error = None
    if request.method == 'POST':
        asignacion = AsignacionCajero.objects.filter(
            pk=_entero(request.POST.get('asignacion')), estado=True
        ).first()
        if asignacion is None:
            error = 'Elegí un cajero asignado a una sucursal.'
        else:
            serializer = CajaSerializer(
                data={'sucursal': asignacion.sucursal_id, 'cajero': asignacion.usuario_id}
            )
            if serializer.is_valid():
                serializer.save()
                return redirect('gestion_cajas')
            error = _errores(serializer)

    context = {
        'usuario': request.user,
        'cajas': Caja.objects.select_related('sucursal', 'cajero').order_by(
            'sucursal__nombre', 'id'
        ),
        'asignaciones': AsignacionCajero.objects.filter(
            estado=True, sucursal__estado=True
        ).select_related('sucursal', 'usuario').order_by(
            'sucursal__nombre', 'usuario__username'
        ),
        'error': error,
    }
    return render(request, 'caja/gestion_cajas.html', context)


@login_required
def caja_abrir_view(request, pk):
    """Abre una caja con su carga inicial de billetes por denominación."""
    _solo_administrador(request)
    caja = Caja.objects.select_related('sucursal', 'cajero').filter(pk=pk).first()
    if caja is None:
        return redirect('gestion_cajas')

    error = None
    if request.method == 'POST':
        try:
            carga = _leer_cantidades(request.POST, 'carga_')
            # El formulario manda todas las denominaciones (muchas en 0); los
            # ceros se descartan porque el service rechaza una carga vacía.
            carga = {billete_id: n for billete_id, n in carga.items() if n > 0}
            services.abrir_caja(caja, sesion.usuario_negocio(request), carga)
            return redirect('gestion_cajas')
        except DjangoValidationError as exc:
            error = ' '.join(exc.messages)

    context = {
        'usuario': request.user,
        'caja': caja,
        'billetes': Billete.objects.filter(estado=True).select_related('moneda'),
        'error': error,
    }
    return render(request, 'caja/caja_abrir.html', context)


# ---------------------------------------------------------------------------
# Cajero: su inventario y el arqueo
# ---------------------------------------------------------------------------

@login_required
def mi_caja_view(request):
    """Inventario de la caja abierta del cajero, por moneda y denominación con
    el total, y el arqueo: el cajero ingresa lo contado y el sistema registra
    la diferencia contra lo esperado (RF106). Solo el rol cajero."""
    if not es_cajero(request.user):
        raise DjangoPermissionDenied('Esta sección es solo para cajeros.')
    usuario = sesion.usuario_negocio(request)
    if usuario is None:
        raise DjangoPermissionDenied('No se encontró tu perfil de usuario.')

    try:
        caja = services.caja_abierta_de(usuario)
    except DjangoValidationError:
        caja = None

    error = None
    if request.method == 'POST':
        moneda = Moneda.objects.filter(
            pk=_entero(request.POST.get('moneda')), estado=True
        ).first()
        if caja is None:
            error = 'No tenés una caja abierta.'
        elif moneda is None:
            error = 'Elegí una moneda válida.'
        else:
            try:
                contados = _leer_cantidades(request.POST, 'contado_')
                arqueo = services.registrar_arqueo(caja, usuario, moneda, contados)
            except DjangoValidationError as exc:
                error = ' '.join(exc.messages)
            else:
                messages.success(
                    request,
                    f'Arqueo de {moneda.codigo} registrado. Diferencia '
                    f'(contado - esperado): {arqueo.diferencia}.',
                )
                return redirect('mi_caja')

    monedas = []
    if caja is not None:
        monedas = services.inventario_por_moneda(caja)
        ids = dict(
            Moneda.objects.filter(
                codigo__in=[g['moneda'] for g in monedas]
            ).values_list('codigo', 'id')
        )
        for grupo in monedas:
            grupo['moneda_id'] = ids.get(grupo['moneda'])

    context = {
        'usuario': request.user,
        'caja': caja,
        'monedas': monedas,
        'arqueos': Arqueo.objects.filter(cajero=usuario).select_related('moneda')[:5],
        'error': error,
    }
    return render(request, 'caja/mi_caja.html', context)