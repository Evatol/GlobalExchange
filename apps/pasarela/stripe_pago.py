"""Cobro con Stripe Checkout: la pasarela de pago real (hoy con claves de prueba).

Es una capa fina sobre la librería ``stripe``: crea la sesión de pago, la consulta, la
expira, devuelve el dinero y verifica los avisos (webhook). No toca el modelo de
negocio: de pasar la operación a pagada o fallida se encarga ``apps.pasarela.views``
con ``apps.transacciones``.

Cómo se cobra:

* La operación se cobra en **guaraníes** (``pyg``): para Stripe es una moneda sin
  decimales, así que el monto va en guaraníes enteros, sin multiplicar por 100.
* El cliente paga en la página de Stripe (**Checkout**): los datos de la tarjeta nunca
  pasan por este sistema.
* La ``referencia_pago_externo`` de la operación es el id de la sesión de Stripe
  (``cs_test_...``).
* El sistema **no confirma por lo que vuelve el navegador**: confirma por lo que
  Stripe dice de esa sesión, consultada con la clave secreta o recibida en un aviso
  con firma verificada.

Solo está activa con ``settings.PASARELA_PROVEEDOR == 'stripe'`` (por defecto, cuando
hay ``STRIPE_SECRET_KEY``). Los errores de Stripe se traducen a ``ErrorStripe``, con un
mensaje que se le puede mostrar al cliente (nunca incluye las claves).
"""

import time
from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings

#: Moneda en que se cobra. El guaraní no tiene decimales (Stripe lo trata así).
MONEDA = 'pyg'

#: Cuánto tiempo puede pagar el cliente en la página de Stripe antes de que expire.
#: Stripe exige entre 30 minutos y 24 horas: una hora deja margen sobre el mínimo.
SEGUNDOS_DE_VIDA_DE_LA_SESION = 60 * 60


class ErrorStripe(Exception):
    """Stripe no pudo atender el pedido. ``str(exc)`` se le puede mostrar al cliente."""


class AvisoInvalido(Exception):
    """El aviso (webhook) no trae una firma válida de Stripe: no se toca nada."""


def activa():
    """True si las compras que no son en efectivo se cobran con Stripe."""
    return settings.PASARELA_PROVEEDOR == 'stripe'


def monto_en_unidades(monto_total):
    """Guaraníes enteros que se le piden a Stripe por un ``monto_total``.

    La base guarda los montos con 2 decimales; el guaraní no tiene centavos y
    Stripe lo trata como moneda sin decimales, así que se redondea al entero.
    """
    return int(Decimal(monto_total).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _llamar(funcion, *args, **kwargs):
    """Llama a la API de Stripe con la clave secreta y traduce sus errores a
    ``ErrorStripe``."""
    if not settings.STRIPE_SECRET_KEY:
        raise ErrorStripe('Stripe no está configurado en este ambiente.')
    try:
        return funcion(*args, api_key=settings.STRIPE_SECRET_KEY, **kwargs)
    except stripe.AuthenticationError as exc:
        raise ErrorStripe(
            'La clave de Stripe configurada no es válida: avisá al administrador.'
        ) from exc
    except stripe.InvalidRequestError as exc:
        raise ErrorStripe(f'Stripe no aceptó el pedido: {exc.user_message or exc}') from exc
    except stripe.StripeError as exc:
        raise ErrorStripe(
            'No se pudo conectar con Stripe. Intentá de nuevo en unos minutos.'
        ) from exc


def crear_sesion(transaccion, url_exito, url_cancelacion):
    """Crea la sesión de Stripe Checkout para pagar una compra y la devuelve.

    ``url_exito`` puede llevar ``{CHECKOUT_SESSION_ID}``, que Stripe reemplaza por el
    id de la sesión al devolver al cliente. La operación viaja como
    ``client_reference_id`` y en los metadatos, para ubicarla desde el panel de Stripe.
    """
    concepto = f'Compra de {transaccion.cantidad:.2f} {transaccion.moneda.codigo}'
    descripcion = f'GlobalExchange · operación #{transaccion.pk}'
    metadatos = {'transaccion_id': str(transaccion.pk)}
    return _llamar(
        stripe.checkout.Session.create,
        mode='payment',
        locale='es',
        client_reference_id=str(transaccion.pk),
        metadata=metadatos,
        line_items=[{
            'quantity': 1,
            'price_data': {
                'currency': MONEDA,
                'unit_amount': monto_en_unidades(transaccion.monto_total),
                'product_data': {'name': concepto, 'description': descripcion},
            },
        }],
        payment_intent_data={'description': descripcion, 'metadata': metadatos},
        expires_at=int(time.time()) + SEGUNDOS_DE_VIDA_DE_LA_SESION,
        success_url=url_exito,
        cancel_url=url_cancelacion,
    )


def obtener_sesion(session_id):
    """La sesión de Stripe tal como está ahora (``status``, ``payment_status``...)."""
    return _llamar(stripe.checkout.Session.retrieve, session_id)


def expirar_sesion(session_id):
    """Cierra una sesión que el cliente todavía no pagó, para que ya no se pueda
    pagar (por ejemplo, si cancela la operación)."""
    return _llamar(stripe.checkout.Session.expire, session_id)


def reembolsar(sesion):
    """Devuelve al cliente lo que pagó en ``sesion``. Es idempotente: pedirlo dos
    veces para la misma sesión devuelve el mismo reembolso, no uno nuevo."""
    return _llamar(
        stripe.Refund.create,
        payment_intent=sesion.payment_intent,
        idempotency_key=f'reembolso-{sesion.id}',
    )


def evento_firmado(cuerpo, firma):
    """El evento de Stripe contenido en ``cuerpo`` (bytes), con la firma verificada
    contra ``STRIPE_WEBHOOK_SECRET``. Lanza ``AvisoInvalido`` si no es de Stripe."""
    try:
        return stripe.Webhook.construct_event(cuerpo, firma, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise AvisoInvalido('Firma de Stripe inválida.') from exc
