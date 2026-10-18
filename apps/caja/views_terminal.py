"""apps/caja/views_terminal.py - pantallas de la terminal de autoservicio (E4-193 y E4-194).

Recorrido del cliente en el quiosco:

1. **Inicio** (``terminal_inicio``, pública): cotizaciones del día y calculadora, sin iniciar
   sesión. Si la terminal no está operativa, avisa y no deja avanzar.
2. **Ingreso** (``terminal_ingreso``): el cliente se identifica con Keycloak. Desde acá la
   sesión queda marcada como de quiosco y ``TerminalSoloAutoservicioMiddleware`` no la deja
   salir de estas pantallas. Si el usuario tiene varios clientes, elige uno
   (``terminal_cliente``); si no tiene ninguno activo, se le explica.
3. **Operar** (``terminal_operar``): compra, venta o cambio en efectivo. Primero ve el cálculo
   (tasa, comisión, total y billetes a ingresar y a retirar) y recién después confirma.
4. **Comprobante** (``terminal_comprobante``): resultado y desglose de billetes.

Salir es un POST a ``oidc_logout``: cierra la sesión de Django y la de Keycloak y, por ser una
sesión de quiosco, vuelve al inicio de la terminal (ver ``apps.usuarios.oidc``).
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.divisas.models import Moneda, TasaCambio
from apps.divisas.views import contexto_de_simulacion
from apps.transacciones.models import Transaccion
from apps.usuarios import sesion

from . import services
from .models import Terminal


def _terminal(pk):
    return get_object_or_404(Terminal.objects.select_related('sucursal', 'caja'), pk=pk)


def _bloqueo(terminal):
    """Motivo por el que la terminal no puede operar, o ``None`` si está operativa."""
    try:
        services.validar_terminal_operativa(terminal)
    except DjangoValidationError as exc:
        return ' '.join(exc.messages)
    return None


def _pantalla_bloqueada(request, terminal, motivo):
    return render(
        request, 'caja/terminal_bloqueada.html', {'terminal': terminal, 'bloqueo': motivo},
        status=409,
    )


def _en_esta_terminal(request, terminal):
    """True si la sesión se identificó en ``terminal`` (pasó por ``terminal_ingreso``)."""
    return sesion.terminal_activa(request) == terminal.pk


@require_http_methods(['GET', 'POST'])
def terminal_inicio_view(request, pk):
    """Pantalla de inicio, pública: cotizaciones del día y simulador (E4-193)."""
    terminal = _terminal(pk)
    motivo = _bloqueo(terminal)
    if motivo:
        return _pantalla_bloqueada(request, terminal, motivo)

    if request.method == 'POST':
        contexto = contexto_de_simulacion(request.POST)
    else:
        contexto = {'tasas': TasaCambio.objects.filter(estado=True).select_related('moneda')}
    contexto['terminal'] = terminal
    contexto['identificado'] = request.user.is_authenticated and _en_esta_terminal(request, terminal)
    return render(request, 'caja/terminal_inicio.html', contexto)


@login_required
def terminal_ingreso_view(request, pk):
    """Destino del login con Keycloak: pone la sesión en modo quiosco y lleva al cliente a
    elegir con quién opera o, si tiene uno solo, a operar (E4-193)."""
    terminal = _terminal(pk)
    sesion.entrar_modo_terminal(request, terminal.pk)

    motivo = _bloqueo(terminal)
    if motivo:
        return _pantalla_bloqueada(request, terminal, motivo)
    if sesion.get_cliente_activo(request) is None:
        # Varios clientes sin elegir uno, o ninguno activo: la pantalla de clientes lo explica.
        return redirect('terminal_cliente', pk=terminal.pk)
    return redirect('terminal_operar', pk=terminal.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def terminal_cliente_view(request, pk):
    """Elección del cliente con el que se opera, cuando el usuario tiene varios. Si no tiene
    ninguno activo, explica por qué no puede operar (E4-193)."""
    terminal = _terminal(pk)
    if not _en_esta_terminal(request, terminal):
        return redirect('terminal_ingreso', pk=terminal.pk)
    motivo = _bloqueo(terminal)
    if motivo:
        return _pantalla_bloqueada(request, terminal, motivo)

    disponibles = list(sesion.clientes_disponibles(request))
    usuario = sesion.usuario_negocio(request)
    error = None
    if disponibles and request.method == 'POST':
        try:
            sesion.set_cliente_activo(request, int(request.POST.get('cliente') or 0))
        except (DjangoPermissionDenied, ValueError):
            error = 'Elegí uno de los clientes de la lista.'
        else:
            return redirect('terminal_operar', pk=terminal.pk)

    return render(request, 'caja/terminal_cliente.html', {
        'terminal': terminal,
        'usuario': usuario,
        'clientes': disponibles,
        'cliente_activo': sesion.get_cliente_activo(request) if disponibles else None,
        # Sin clientes activos: o no tiene ninguno asociado o todos están dados de baja.
        'todos_inactivos': not disponibles and usuario is not None
        and usuario.clientes.filter(estado=False).exists(),
        'error': error,
    })


def _parametros(post):
    return dict(
        tipo=post.get('tipo', 'COMPRA'),
        moneda_codigo=post.get('moneda_codigo'),
        cantidad=post.get('cantidad'),
        moneda_destino_codigo=post.get('moneda_destino_codigo') or None,
    )


@login_required
@require_http_methods(['GET', 'POST'])
def terminal_operar_view(request, pk):
    """Compra, venta o cambio en efectivo en la terminal (E4-194).

    Dos pasos: **calcular** muestra tasa, comisión, total y los billetes que el cliente tiene
    que ingresar y los que la terminal le va a entregar; **confirmar** registra la operación
    y los movimientos de billetes de la caja de la terminal. Si falla (stock de la terminal,
    límite de la categoría, cotización que cambió) no se mueve ningún billete y el intento
    queda como ``FALLIDA``.
    """
    terminal = _terminal(pk)
    if not _en_esta_terminal(request, terminal):
        return redirect('terminal_ingreso', pk=terminal.pk)
    motivo = _bloqueo(terminal)
    if motivo:
        return _pantalla_bloqueada(request, terminal, motivo)
    cliente = sesion.get_cliente_activo(request)
    if cliente is None:
        return redirect('terminal_cliente', pk=terminal.pk)

    usuario = sesion.usuario_negocio(request)
    error, fallida, vista_previa = None, None, None
    datos = request.POST if request.method == 'POST' else {}
    if request.method == 'POST':
        parametros = _parametros(request.POST)
        try:
            if request.POST.get('accion') == 'confirmar':
                transaccion = services.registrar_operacion_en_terminal(
                    terminal=terminal, usuario=usuario, cliente=cliente, **parametros
                )
                return redirect('terminal_comprobante', pk=terminal.pk, transaccion_id=transaccion.pk)
            transaccion, billetes = services.previsualizar_operacion_en_terminal(
                terminal=terminal, usuario=usuario, cliente=cliente, **parametros
            )
            vista_previa = {'transaccion': transaccion, 'billetes': billetes}
        except DjangoValidationError as exc:
            error = ' '.join(exc.messages)
            fallida = getattr(exc, 'transaccion_fallida', None)

    return render(request, 'caja/terminal_operar.html', {
        'terminal': terminal,
        'cliente': cliente,
        'varios_clientes': sesion.clientes_disponibles(request).count() > 1,
        'monedas': Moneda.objects.filter(estado=True, tasas__estado=True).distinct().order_by('codigo'),
        'datos': datos,
        'vista_previa': vista_previa,
        'error': error,
        'fallida': fallida,
    })


@login_required
def terminal_comprobante_view(request, pk, transaccion_id):
    """Comprobante de una operación hecha en esta terminal, con el desglose de billetes.
    Solo la ve quien la hizo (E4-194)."""
    terminal = _terminal(pk)
    if not _en_esta_terminal(request, terminal):
        return redirect('terminal_ingreso', pk=terminal.pk)

    usuario = sesion.usuario_negocio(request)
    transaccion = get_object_or_404(
        Transaccion.objects.select_related('cliente', 'moneda', 'moneda_destino'),
        pk=transaccion_id, usuario=usuario, modalidad=services.MODALIDAD_TERMINAL,
    )
    return render(request, 'caja/terminal_comprobante.html', {
        'terminal': terminal,
        't': transaccion,
        'usuario': usuario,
        'billetes': services.movimientos_de_la_operacion(transaccion),
    })
