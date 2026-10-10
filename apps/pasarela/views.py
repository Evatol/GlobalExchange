"""Pasarela de pago simulada (E4-157/E4-158).

Hace de "empresa de pagos" externa para poder probar y mostrar el flujo de
confirmación de pago completo sin un proveedor real, y sin comandos: el cliente
pide pagar una compra, llega a esta pantalla, y según lo que elija la pasarela le
avisa al sistema, que confirma o rechaza la operación.

Se comporta como una pasarela real en lo que importa:

* El sistema **no confirma por lo que vuelve el navegador** sino por el aviso de la
  pasarela (el webhook): el cliente podría volver sin haber pagado.
* El aviso va **firmado** (HMAC-SHA256, ``apps.transacciones.webhook``) y lo
  verifica el mismo código que verifica los avisos que llegan por HTTP
  (``procesar_aviso_de_pago``). Se entrega sin salir del proceso: no depende de la
  URL del servidor ni de cuántos procesos tenga.

Para pasar a un proveedor real (Bancard, Pagopar, Stripe...) se reemplaza esta
pantalla por la página de pago del proveedor y se agrega la verificación de firma de
ese proveedor; el resto del flujo no cambia.

Solo está disponible si ``settings.PASARELA_SIMULADA_ACTIVA``: nunca debe estar
encendida en un ambiente que cobre de verdad, porque deja "pagar" sin pagar.
"""

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.transacciones import webhook
from apps.transacciones.models import Transaccion
from apps.transacciones.views import procesar_aviso_de_pago
from apps.usuarios import sesion


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


@login_required
@require_http_methods(['GET', 'POST'])
def pagar_view(request, referencia):
    """Pantalla de pago de la pasarela simulada.

    ``GET`` muestra el monto y los botones Pagar y Rechazar. ``POST`` firma el
    aviso correspondiente, se lo entrega al sistema y devuelve al cliente al
    resumen de su operación con el resultado.
    """
    if not settings.PASARELA_SIMULADA_ACTIVA:
        raise Http404('La pasarela simulada no está habilitada en este ambiente.')
    transaccion = _transaccion_de_la_referencia(request, referencia)

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
