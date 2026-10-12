"""apps/caja/views_pantallas.py - pantallas HTML de RF106 (inventario y arqueo).

Propias del portal, en vez de la API navegable de DRF. Reutilizan los
serializers y los services de ``views_billetes`` para no duplicar reglas.
"""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.divisas.models import Moneda
from apps.usuarios import sesion
from apps.usuarios.models import Cliente
from apps.usuarios.permissions import es_cajero

from . import services
from .models import (
    Arqueo, AsignacionCajero, Billete, Caja, CierreCaja, LimiteStock, MovimientoBillete,
)
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


def _limite_o_none(texto):
    """``Decimal`` a partir de lo escrito en el formulario; vacío es ``None``
    (sin límite). Lanza ``ValidationError`` si no es un número."""
    texto = texto.strip().replace(',', '.')
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise DjangoValidationError(f'"{texto}" no es un número.')
    if not valor.is_finite():
        raise DjangoValidationError(f'"{texto}" no es un número.')
    return valor


@login_required
def gestion_limites_stock_view(request):
    """Límites mínimo y máximo de stock de billetes por moneda (RF107), solo
    administrador. Una fila por moneda activa; vacío es "sin límite" y borra el
    que hubiera. Se guarda todo o nada: si una fila tiene un error no se
    modifica ninguna, y se vuelve a mostrar lo que se escribió con el motivo."""
    _solo_administrador(request)
    monedas = list(Moneda.objects.filter(estado=True).order_by('codigo'))
    existentes = {limite.moneda_id: limite for limite in LimiteStock.objects.all()}

    errores, escrito = [], {}
    if request.method == 'POST':
        nuevos = {}
        for moneda in monedas:
            minimo_txt = request.POST.get(f'minimo_{moneda.id}', '')
            maximo_txt = request.POST.get(f'maximo_{moneda.id}', '')
            escrito[moneda.id] = (minimo_txt, maximo_txt)
            try:
                limite = LimiteStock(
                    moneda=moneda, minimo=_limite_o_none(minimo_txt), maximo=_limite_o_none(maximo_txt)
                )
                limite.clean()
            except DjangoValidationError as exc:
                errores.append(f'{moneda.codigo}: {" ".join(exc.messages)}')
            else:
                nuevos[moneda.id] = limite
        if not errores:
            for moneda in monedas:
                limite = nuevos[moneda.id]
                if limite.minimo is None and limite.maximo is None:
                    LimiteStock.objects.filter(moneda=moneda).delete()
                else:
                    LimiteStock.objects.update_or_create(
                        moneda=moneda, defaults={'minimo': limite.minimo, 'maximo': limite.maximo}
                    )
            messages.success(request, 'Límites de stock guardados.')
            return redirect('gestion_limites_stock')

    filas = []
    for moneda in monedas:
        if moneda.id in escrito:
            minimo, maximo = escrito[moneda.id]
        else:
            actual = existentes.get(moneda.id)
            minimo = '' if actual is None or actual.minimo is None else f'{actual.minimo:f}'
            maximo = '' if actual is None or actual.maximo is None else f'{actual.maximo:f}'
        filas.append({'moneda': moneda, 'minimo': minimo, 'maximo': maximo})
    return render(request, 'caja/gestion_limites_stock.html', {
        'usuario': request.user, 'filas': filas, 'errores': errores,
    })


@login_required
def caja_balance_view(request, pk):
    """Balance de la sesión de una caja y su historial de cierres (E4-100),
    solo administrador. Desde acá el administrador también puede cerrarla."""
    _solo_administrador(request)
    caja = Caja.objects.select_related('sucursal', 'cajero').filter(pk=pk).first()
    if caja is None:
        return redirect('gestion_cajas')
    return render(request, 'caja/caja_balance.html', {
        'usuario': request.user,
        'caja': caja,
        'balance': services.balance_caja(caja),
        'cierres': caja.cierres.prefetch_related('detalles__moneda')[:10],
        'movimientos': MovimientoBillete.objects.filter(caja=caja).select_related(
            'billete__moneda', 'usuario', 'transaccion'
        ).order_by('-fecha_hora', '-id')[:15],
    })


@login_required
@require_POST
def caja_cerrar_admin_view(request, pk):
    """El administrador cierra una caja abierta sin contarla (E4-100). Si hay
    que contar, el cajero cierra la suya desde ``Mi Caja``."""
    _solo_administrador(request)
    caja = Caja.objects.filter(pk=pk).first()
    if caja is None:
        return redirect('gestion_cajas')
    usuario = sesion.usuario_negocio(request)
    if usuario is None:
        messages.error(request, 'No se encontró tu perfil de usuario.')
    else:
        try:
            services.cerrar_caja(caja, usuario)
            messages.success(request, f'Caja #{caja.pk} cerrada.')
        except DjangoValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
    return redirect('caja_balance', pk=pk)


# ---------------------------------------------------------------------------
# Cajero: su inventario, el arqueo, el mostrador y el cierre
# ---------------------------------------------------------------------------

def _cajero_y_caja(request):
    """``(usuario, caja_abierta_o_None)`` del cajero que hace el request.
    Lanza 403 si no es cajero o no tiene perfil de usuario."""
    if not es_cajero(request.user):
        raise DjangoPermissionDenied('Esta sección es solo para cajeros.')
    usuario = sesion.usuario_negocio(request)
    if usuario is None:
        raise DjangoPermissionDenied('No se encontró tu perfil de usuario.')
    try:
        return usuario, services.caja_abierta_de(usuario)
    except DjangoValidationError:
        return usuario, None


@login_required
def mostrador_view(request):
    """Atender a un cliente en el mostrador (E4-101): compra, venta o cambio
    en efectivo.

    Dos pasos: **calcular** muestra los montos y los billetes que la caja
    tiene que recibir y entregar (los arma el sistema); **confirmar** registra
    la operación y, solo, los movimientos de billetes y el stock. Si algo no
    cierra (stock, límite del cliente, cotización) no queda nada guardado.
    """
    usuario, caja = _cajero_y_caja(request)

    error, vista_previa = None, None
    datos = request.POST if request.method == 'POST' else {}
    if caja is None:
        error = 'No tenés una caja abierta. Pedile al administrador que abra tu caja.'
    elif request.method == 'POST':
        confirmar = request.POST.get('accion') == 'confirmar'
        try:
            cliente = Cliente.objects.filter(
                documento=request.POST.get('documento', '').strip()
            ).first()
            if cliente is None:
                raise DjangoValidationError('No existe un cliente con ese documento.')
            parametros = dict(
                cliente=cliente,
                tipo=request.POST.get('tipo', 'COMPRA'),
                moneda_codigo=request.POST.get('moneda_codigo'),
                cantidad=request.POST.get('cantidad'),
                moneda_destino_codigo=request.POST.get('moneda_destino_codigo') or None,
            )
            if confirmar:
                transaccion = services.registrar_operacion_presencial(
                    caja=caja, usuario=usuario, **parametros
                )
                messages.success(
                    request,
                    f'Operación #{transaccion.pk} confirmada. Los billetes recibidos y '
                    f'entregados se registraron automáticamente.',
                )
                return redirect('mi_caja')
            transaccion, esperado = services.previsualizar_operacion_presencial(**parametros)
            vista_previa = {
                'cliente': cliente,
                'transaccion': transaccion,
                'billetes': services.sugerir_billetes(caja, transaccion),
            }
        except DjangoValidationError as exc:
            error = ' '.join(exc.messages)

    return render(request, 'caja/mostrador.html', {
        'usuario': request.user,
        'caja': caja,
        'alertas': services.alertas_de_stock(caja) if caja is not None else [],
        'monedas': Moneda.objects.filter(estado=True, tasas__estado=True).distinct().order_by('codigo'),
        'datos': datos,
        'vista_previa': vista_previa,
        'error': error,
    })


@login_required
def caja_cerrar_view(request):
    """El cajero cierra su caja (E4-100): ve el balance de la sesión y, si
    quiere, cuenta los billetes de una o más monedas (queda un arqueo con su
    diferencia). Una moneda que deja sin completar no se cuenta."""
    usuario, caja = _cajero_y_caja(request)
    if caja is None:
        messages.error(request, 'No tenés una caja abierta.')
        return redirect('mi_caja')

    inventario = services.inventario_por_moneda(caja)
    ids = dict(
        Moneda.objects.filter(codigo__in=[g['moneda'] for g in inventario]).values_list('codigo', 'id')
    )
    for grupo in inventario:
        grupo['moneda_id'] = ids.get(grupo['moneda'])

    error = None
    if request.method == 'POST':
        try:
            cantidades = _leer_cantidades(request.POST, 'contado_')
            contados = {}
            for grupo in inventario:
                billetes = [d['billete_id'] for d in grupo['denominaciones']]
                if any(request.POST.get(f'contado_{i}', '').strip() for i in billetes):
                    contados[grupo['moneda_id']] = {i: cantidades.get(i, 0) for i in billetes}
            cierre = services.cerrar_caja(caja, usuario, contados)
        except DjangoValidationError as exc:
            error = ' '.join(exc.messages)
        else:
            con_diferencia = [d.moneda.codigo for d in cierre.detalles.all() if d.diferencia]
            aviso = (
                f' Con diferencia en: {", ".join(con_diferencia)}.' if con_diferencia else ''
            )
            messages.success(request, f'Caja #{caja.pk} cerrada.{aviso}')
            return redirect('mi_caja')

    return render(request, 'caja/caja_cerrar.html', {
        'usuario': request.user,
        'caja': caja,
        'balance': services.balance_caja(caja),
        'monedas': inventario,
        'error': error,
    })

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

    ultimo_cierre = (
        CierreCaja.objects.filter(cajero=usuario).prefetch_related('detalles__moneda').first()
        if caja is None else None
    )
    context = {
        'usuario': request.user,
        'caja': caja,
        'monedas': monedas,
        'balance': services.balance_caja(caja) if caja is not None else None,
        'movimientos': (
            MovimientoBillete.objects.filter(caja=caja).select_related('billete__moneda', 'transaccion')
            .order_by('-fecha_hora', '-id')[:10] if caja is not None else []
        ),
        'ultimo_cierre': ultimo_cierre,
        'ultimo_cierre_lista': [ultimo_cierre] if ultimo_cierre else [],
        'arqueos': Arqueo.objects.filter(cajero=usuario).select_related('moneda')[:5],
        'error': error,
    }
    return render(request, 'caja/mi_caja.html', context)