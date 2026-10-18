"""apps/facturacion/views.py - pantallas de consulta y descarga de facturas (Sprint 5).

Pantallas propias del portal, con el mismo criterio de alcance que el
historial de transacciones: administrador y analista consultan las facturas de
todos los clientes (solo lectura) y el resto, únicamente las de su cliente
activo. Las reglas viven en ``apps.facturacion.services``.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.divisas.models import Moneda
from apps.usuarios import sesion

from . import services
from .models import Factura


def _denegar(request, mensaje):
    """Responde 403 con una pantalla que explica el motivo."""
    contexto = {'usuario': request.user, 'mensaje': mensaje}
    return render(request, 'facturacion/acceso_denegado.html', contexto, status=403)


def _factura_o_404(pk):
    return get_object_or_404(
        Factura.objects.select_related(
            'transaccion__cliente',
            'transaccion__moneda',
            'transaccion__moneda_destino',
            'transaccion__metodo_pago',
        ),
        pk=pk,
    )


@login_required
@require_GET
def lista_facturas_view(request):
    """Listado de facturas con filtros por fecha, número, moneda y estado."""
    visibles = services.facturas_visibles(request)
    facturas, errores = services.filtrar_facturas(visibles, request.GET)
    estados = sorted(
        set(visibles.values_list('estado', flat=True)) | {Factura.ESTADO_EMITIDA}
    )

    ve_todas = services.puede_ver_todas(request.user)
    context = {
        'usuario': request.user,
        'facturas': facturas,
        'estados': estados,
        'monedas': Moneda.objects.filter(estado=True).order_by('codigo'),
        'filtros': {
            'fecha_desde': request.GET.get('fecha_desde', ''),
            'fecha_hasta': request.GET.get('fecha_hasta', ''),
            'numero': request.GET.get('numero', ''),
            'moneda': request.GET.get('moneda', ''),
            'estado': request.GET.get('estado', '').upper(),
        },
        'errores': errores,
        've_todas': ve_todas,
        'sin_cliente_activo': not ve_todas and sesion.get_cliente_activo(request) is None,
    }
    return render(request, 'facturacion/lista_facturas.html', context)


@login_required
@require_GET
def detalle_factura_view(request, pk):
    """Detalle de una factura: montos, tasas, comisiones y transacción asociada."""
    factura = _factura_o_404(pk)
    motivo = services.motivo_de_denegacion(request, factura)
    if motivo:
        return _denegar(request, motivo)

    context = {
        'usuario': request.user,
        'factura': factura,
        'transaccion': factura.transaccion,
        'cliente': factura.transaccion.cliente,
        'puede_descargar': factura.esta_emitida,
    }
    return render(request, 'facturacion/detalle_factura.html', context)


@login_required
@require_GET
def descargar_factura_pdf_view(request, pk):
    """Descarga el PDF de una factura emitida."""
    factura = _factura_o_404(pk)
    motivo = services.motivo_de_denegacion(request, factura, descarga=True)
    if motivo:
        return _denegar(request, motivo)

    respuesta = HttpResponse(services.generar_pdf(factura), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'attachment; filename="factura-{factura.numero}.pdf"'
    return respuesta