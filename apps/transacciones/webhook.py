"""Firma de los mensajes entre la pasarela de pago externa y el webhook
(E4-157/E4-158).

El webhook es una puerta abierta a internet: sin login ni sesión. Lo único que
prueba que un mensaje viene de la pasarela es la firma: un HMAC-SHA256 del
cuerpo, calculado con el secreto que comparten (``WEBHOOK_PAGO_SECRET``) y
enviado en el encabezado ``X-Signature``. El mismo código firma (la pasarela
simulada, ``manage.py simular_webhook_pago``) y verifica (el webhook), para que
no puedan desalinearse.
"""

import hashlib
import hmac

from django.conf import settings

ENCABEZADO_FIRMA = 'X-Signature'


def firmar(cuerpo, secreto=None):
    """Firma hexadecimal HMAC-SHA256 de ``cuerpo`` (bytes)."""
    secreto = settings.WEBHOOK_PAGO_SECRET if secreto is None else secreto
    return hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def firma_valida(cuerpo, firma_recibida):
    """True si ``firma_recibida`` corresponde a ``cuerpo``.

    Sin secreto configurado nunca es válida (aceptar todo sería peor que no
    funcionar). Acepta el prefijo ``sha256=`` y compara en tiempo constante,
    para no filtrar la firma por diferencias de tiempo.
    """
    if not settings.WEBHOOK_PAGO_SECRET or not firma_recibida:
        return False
    firma_recibida = firma_recibida.removeprefix('sha256=').strip().lower()
    return hmac.compare_digest(firmar(cuerpo), firma_recibida)
