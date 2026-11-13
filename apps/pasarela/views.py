"""Pasarelas de pago: Stripe (real, con claves de prueba) y una simulada (E4-157/E4-158).

**Stripe** (``apps.pasarela.stripe_pago``) es la pasarela de las compras que no son en
efectivo. El cliente paga en la página de Stripe y el sistema se entera de dos
maneras, que llevan al mismo código y son idempotentes:

* cuando el cliente **vuelve** de Stripe (``stripe_retorno_view``);
* por el **aviso de Stripe** (``stripe_webhook_view``), que llega aunque el cliente
  haya cerrado la pestaña antes de volver.

En ninguna de las dos se confía en lo que trae el navegador: se consulta la sesión a
Stripe con la clave secreta, o se verifica la firma del aviso. Si el cliente pagó pero
la operación ya no se puede realizar (cambió la cotización, o la canceló justo antes),
el pago se devuelve solo.

**La pasarela simulada** hace de "empresa de pagos" externa para poder probar y mostrar
el flujo de confirmación de pago sin un proveedor real, y sin comandos: el cliente pide
pagar una compra, llega a esa pantalla, y según lo que elija la pasarela le avisa al
sistema, que confirma o rechaza la operación. El aviso va **firmado** (HMAC-SHA256,
``apps.transacciones.webhook``) y lo verifica el mismo código que verifica los avisos
que llegan por HTTP (``procesar_aviso_de_pago``). Solo está disponible si
``settings.PASARELA_SIMULADA_ACTIVA``: nunca debe estar encendida en un ambiente que
cobre de verdad, porque deja "pagar" sin pagar.

Las dos terminan en ``aplicar_aviso_de_pago``, así que el resto del flujo (confirmar,
cancelar si cambió la cotización, dejar fallida) es el mismo.
"""

import json
import logging
from typing import NamedTuple

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.transacciones import webhook
from apps.transacciones.models import Transaccion
from apps.transacciones.views import aplicar_aviso_de_pago, procesar_aviso_de_pago
from apps.usuarios import sesion

from . import stripe_pago

logger = logging.getLogger(__name__)

# Avisos de Stripe que dicen algo del pago de una sesión de Checkout.
EVENTOS_DE_PAGO = (
    'checkout.session.completed',
    'checkout.session.async_payment_succeeded',
    'checkout.session.async_payment_failed',
    'checkout.session.expired',
)


def _transaccion_de_la_referencia(request, referencia):
    """Operación del cliente activo con esa referencia de pago, o ``Http404``.

    Cada cliente solo llega a la pasarela de sus propias operaciones: sin eso,
    conociendo una referencia se podría "pagar" la operación de otro.
    """
    cliente = sesion.get_cliente_activo(request)
    transaccion = (
        Transaccion.objects.select_related('moneda', 'cliente')
        .filter(referencia_pago_externo=referencia, cliente=cliente).first()
        if cliente is not None else None
    )
    if transaccion is None:
        raise Http404('No existe un pago con esa referencia para tu cliente activo.')
    return transaccion


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

class ResultadoDeStripe(NamedTuple):
    """Lo que pasó al aplicar el estado de una sesión de Stripe a su operación.

    ``evento`` es ``PAGADO``, ``RECHAZADO`` o ``None`` (Stripe todavía no dice nada del
    pago); ``datos`` y ``codigo`` son la respuesta de ``aplicar_aviso_de_pago`` (``None``
    si no hubo evento); ``devuelto`` es True si el cliente pagó, la operación no se pudo
    realizar y el pago se le devolvió.
    """

    evento: str | None
    datos: dict | None
    codigo: int | None
    devuelto: bool


def _evento_de_la_sesion(sesion_stripe, tipo_evento):
    """``PAGADO``, ``RECHAZADO`` o ``None`` según lo que Stripe dice de la sesión."""
    if sesion_stripe.payment_status in ('paid', 'no_payment_required'):
        return 'PAGADO'
    if tipo_evento == 'checkout.session.async_payment_failed' or sesion_stripe.status == 'expired':
        return 'RECHAZADO'
    return None


def _devolver_pago_no_realizado(sesion_stripe):
    """Si el cliente pagó una operación que ya no se puede realizar (``CANCELADA`` o
    ``FALLIDA``), le devuelve el pago. Devuelve True si hizo la devolución.

    Si Stripe no puede devolverlo ahora, la operación queda anotada para devolverlo a
    mano y el error sigue subiendo: el webhook responde error y Stripe reintenta.
    """
    transaccion = Transaccion.objects.filter(referencia_pago_externo=sesion_stripe.id).first()
    if transaccion is None or transaccion.estado not in ('CANCELADA', 'FALLIDA'):
        return False
    try:
        reembolso = stripe_pago.reembolsar(sesion_stripe)
    except stripe_pago.ErrorStripe:
        transaccion.anotar_devolucion()
        raise
    transaccion.anotar_devolucion(reembolso.id)
    return True


def sincronizar_con_stripe(sesion_stripe, tipo_evento=None):
    """Aplica a la operación de esa sesión lo que Stripe dice del pago.

    ``sesion_stripe`` tiene que venir de Stripe (consultada con la clave secreta o
    dentro de un aviso con firma verificada), nunca armada con datos del navegador.
    ``tipo_evento`` es el tipo del aviso (si lo hubo). Es idempotente: se puede llamar
    cuantas veces haga falta con la misma sesión.
    """
    evento = _evento_de_la_sesion(sesion_stripe, tipo_evento)
    if evento is None:
        return ResultadoDeStripe(None, None, None, False)
    motivo = None
    if evento == 'RECHAZADO':
        motivo = (
            'Stripe no pudo cobrar el pago.'
            if tipo_evento == 'checkout.session.async_payment_failed'
            else 'La sesión de pago de Stripe venció sin que se cobrara.'
        )
    datos, codigo = aplicar_aviso_de_pago(sesion_stripe.id, evento, motivo)
    devuelto = evento == 'PAGADO' and _devolver_pago_no_realizado(sesion_stripe)
    return ResultadoDeStripe(evento, datos, codigo, devuelto)


def _informar_resultado_de_stripe(request, transaccion, resultado):
    """Le cuenta al cliente, con un mensaje, cómo terminó el pago."""
    if resultado.evento is None:
        messages.info(
            request,
            'Todavía no recibimos el pago de Stripe. Si ya pagaste, esperá unos segundos '
            'y recargá esta página.',
        )
    elif resultado.evento == 'PAGADO' and resultado.codigo == 200:
        messages.success(
            request,
            f'Pago confirmado con Stripe. La operación #{transaccion.pk} se realizó con éxito.',
        )
    elif resultado.evento == 'PAGADO':
        messages.error(request, resultado.datos['detail'])  # ej. cambió la cotización
        if resultado.devuelto:
            messages.info(request, 'El pago que hiciste en Stripe se te devuelve completo.')
    elif resultado.codigo == 200:
        messages.error(
            request,
            f'Stripe no cobró el pago. La operación #{transaccion.pk} quedó fallida.',
        )


def _continuar_pago_con_stripe(request, transaccion):
    """Lleva al cliente a la página de Stripe para pagar (o retomar) esta operación.

    Si la sesión ya no está abierta, en cambio, aplica lo que Stripe dice (pagó, o
    venció) y vuelve al resumen de la operación.
    """
    resumen = redirect('operacion_detalle', pk=transaccion.pk)
    if transaccion.estado != 'PENDIENTE_PAGO':
        messages.info(request, 'Esa operación ya no espera un pago.')
        return resumen
    try:
        sesion_stripe = stripe_pago.obtener_sesion(transaccion.referencia_pago_externo)
        if sesion_stripe.status == 'open':
            return redirect(sesion_stripe.url)
        _informar_resultado_de_stripe(
            request, transaccion, sincronizar_con_stripe(sesion_stripe)
        )
    except stripe_pago.ErrorStripe as exc:
        messages.error(request, str(exc))
    return resumen


@login_required
@require_GET
def stripe_retorno_view(request):
    """A donde Stripe devuelve al cliente después de pagar (``?session_id=...``).

    No da por pagada la operación por haber vuelto: consulta la sesión a Stripe y
    aplica lo que Stripe dice. La sesión tiene que ser de una operación del cliente
    activo (si no, 404).
    """
    transaccion = _transaccion_de_la_referencia(request, request.GET.get('session_id', ''))
    try:
        sesion_stripe = stripe_pago.obtener_sesion(transaccion.referencia_pago_externo)
        _informar_resultado_de_stripe(
            request, transaccion, sincronizar_con_stripe(sesion_stripe)
        )
    except stripe_pago.ErrorStripe as exc:
        logger.warning('No se pudo confirmar con Stripe la operación %s: %s', transaccion.pk, exc)
        messages.error(request, str(exc))
    return redirect('operacion_detalle', pk=transaccion.pk)


@csrf_exempt
@require_POST
def stripe_webhook_view(request):
    """``POST /api/pasarela/stripe/webhook/``: avisos de Stripe sobre los pagos.

    No usa login ni sesión (Stripe no tiene usuario): la autenticidad la da la firma del
    encabezado ``Stripe-Signature``, verificada con ``STRIPE_WEBHOOK_SECRET``. Responde
    200 a todo aviso válido, también a los que no nos tocan (otro tipo de evento, o de
    una sesión que no es de este sistema), para que Stripe no los reintente. Si algo
    falla de nuestro lado responde error y Stripe lo reintenta.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        return JsonResponse({'detail': 'El webhook de Stripe no está configurado.'}, status=503)
    try:
        aviso = stripe_pago.evento_firmado(
            request.body, request.headers.get('Stripe-Signature', '')
        )
    except stripe_pago.AvisoInvalido as exc:
        return JsonResponse({'detail': str(exc)}, status=400)

    if aviso.type not in EVENTOS_DE_PAGO:
        return JsonResponse({'detail': 'Evento ignorado.'})
    sesion_stripe = aviso.data.object
    if not Transaccion.objects.filter(referencia_pago_externo=sesion_stripe.id).exists():
        return JsonResponse({'detail': 'No es una operación de este sistema: ignorado.'})
    resultado = sincronizar_con_stripe(sesion_stripe, aviso.type)
    return JsonResponse({'detail': 'Aviso procesado.', 'evento': resultado.evento})


# ---------------------------------------------------------------------------
# Pasarela simulada
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(['GET', 'POST'])
def pagar_view(request, referencia):
    """Pantalla de pago de la operación con esa referencia.

    Si la operación se paga con Stripe, lleva al cliente a la página de Stripe. Si no,
    es la pantalla de la pasarela simulada: ``GET`` muestra el monto y los botones Pagar
    y Rechazar; ``POST`` firma el aviso correspondiente, se lo entrega al sistema y
    devuelve al cliente al resumen de su operación con el resultado.
    """
    transaccion = _transaccion_de_la_referencia(request, referencia)
    if transaccion.proveedor_pago == Transaccion.PROVEEDOR_STRIPE:
        return _continuar_pago_con_stripe(request, transaccion)
    if not settings.PASARELA_SIMULADA_ACTIVA:
        raise Http404('La pasarela simulada no está habilitada en este ambiente.')

    if request.method == 'GET':
        return render(request, 'pasarela/pagar.html', {
            'transaccion': transaccion,
            'espera_pago': transaccion.estado == 'PENDIENTE_PAGO',
        })

    if transaccion.estado != 'PENDIENTE_PAGO':
        messages.info(request, 'Esa operación ya no espera un pago.')
        return redirect('operacion_detalle', pk=transaccion.pk)

    accion = request.POST.get('accion')
    if accion not in ('pagar', 'rechazar'):
        messages.error(request, 'Elegí Pagar o Rechazar.')
        return redirect('pasarela_pagar', referencia=referencia)

    cuerpo = json.dumps({
        'referencia': referencia,
        'estado': 'PAGADO' if accion == 'pagar' else 'RECHAZADO',
    }).encode()
    datos, codigo = procesar_aviso_de_pago(cuerpo, webhook.firmar(cuerpo))

    if codigo == 200 and accion == 'pagar':
        messages.success(
            request, f'Pago confirmado. La operación #{transaccion.pk} se realizó con éxito.'
        )
    elif codigo == 200:
        messages.error(
            request, f'La pasarela rechazó el pago. La operación #{transaccion.pk} quedó fallida.'
        )
    elif codigo == 409:
        messages.error(request, datos['detail'])  # ej. cambió la cotización antes del pago
    else:
        messages.error(request, f'No se pudo registrar el pago: {datos["detail"]}')
    return redirect('operacion_detalle', pk=transaccion.pk)
