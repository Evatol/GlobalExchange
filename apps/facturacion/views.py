"""Pantallas de facturas electrónicas: listado con filtros, detalle y descarga en PDF.

Quién ve qué:

* El ``usuario_final`` solo ve las facturas del **cliente activo** de su sesión, y solo
  puede abrir (detalle y PDF) las que ya están ``EMITIDA``: en el listado también
  aparecen las pendientes, para que sepa que van a salir.
* ``analista`` y ``administrador`` consultan las de **todos** los clientes, solo lectura
  (las pantallas no modifican nada). Pueden abrir el detalle de cualquier estado, con el
  estado del envío para soporte, y descargar el PDF de las emitidas.
* Nadie descarga el PDF de una factura que no está emitida (todavía no tiene validez).

Pedir una factura ajena, inexistente o no emitida devuelve al listado con el mismo
mensaje, para no revelar si existe.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from apps.divisas.models import Moneda
from apps.usuarios import sesion
from apps.usuarios.models import Cliente
from apps.usuarios.permissions import ADMINISTRADOR, ANALISTA, tiene_rol

from .models import Factura
from .pdf import generar_pdf
from .services import HORA_DE_PARAGUAY

MENSAJE_SIN_ACCESO = 'No tenés acceso a esa factura o todavía no fue emitida.'
NUMERO_MAXIMO = 2_147_483_647  # tope del campo entero de la base


def _ve_todas(usuario):
    return tiene_rol(usuario, (ADMINISTRADOR, ANALISTA))


def _facturas_visibles(request):
    """Las facturas que este usuario puede consultar (ver el módulo)."""
    facturas = Factura.objects.select_related(
        'transaccion__cliente', 'transaccion__moneda', 'transaccion__moneda_destino',
        'transaccion__metodo_pago', 'transaccion__medio_pago',
    )
    if _ve_todas(request.user):
        return facturas
    cliente = sesion.get_cliente_activo(request)
    return facturas.filter(transaccion__cliente=cliente) if cliente else facturas.none()


def _factura_accesible(request, pk, para_pdf=False):
    """La factura ``pk`` si este usuario puede abrirla, o ``None``."""
    factura = _facturas_visibles(request).filter(pk=pk).first()
    if factura is None:
        return None
    if not factura.esta_emitida and (para_pdf or not _ve_todas(request.user)):
        return None
    return factura


def _fecha(texto):
    """La fecha ``AAAA-MM-DD`` escrita en el filtro, o ``None`` si no es una fecha válida
    (``parse_date`` también lanza error con fechas imposibles como 2026-99-99)."""
    try:
        return parse_date(texto)
    except ValueError:
        return None


def _filtrar_por_numero(facturas, texto):
    """``12`` o ``001-001-0000012``. Un texto que no es un número no coincide con nada."""
    partes = texto.split('-')
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        establecimiento, punto, numero = partes
        numero = int(numero)
        if numero > NUMERO_MAXIMO:
            return facturas.none()
        return facturas.filter(
            establecimiento=establecimiento.zfill(3), punto_expedicion=punto.zfill(3),
            numero=numero,
        )
    if texto.isdigit() and int(texto) <= NUMERO_MAXIMO:
        return facturas.filter(numero=int(texto))
    return facturas.none()


@login_required
@require_GET
def facturas_view(request):
    """Listado de facturas con filtros por fecha, número, moneda y estado (y por cliente,
    para quien ve las de todos)."""
    ve_todas = _ve_todas(request.user)
    facturas = _facturas_visibles(request)

    filtros = {
        nombre: request.GET.get(nombre, '').strip()
        for nombre in ('fecha_desde', 'fecha_hasta', 'numero', 'moneda', 'estado', 'cliente')
    }
    desde, hasta = _fecha(filtros['fecha_desde']), _fecha(filtros['fecha_hasta'])
    if desde:
        facturas = facturas.filter(fecha_emision__date__gte=desde)
    if hasta:
        facturas = facturas.filter(fecha_emision__date__lte=hasta)
    if filtros['numero']:
        facturas = _filtrar_por_numero(facturas, filtros['numero'])
    if filtros['moneda'].isdigit():
        facturas = facturas.filter(
            Q(transaccion__moneda_id=filtros['moneda'])
            | Q(transaccion__moneda_destino_id=filtros['moneda'])
        )
    if filtros['estado'] in dict(Factura.ESTADOS):
        facturas = facturas.filter(estado=filtros['estado'])
    if ve_todas and filtros['cliente'].isdigit():
        facturas = facturas.filter(transaccion__cliente_id=filtros['cliente'])

    facturas = list(facturas)
    for factura in facturas:
        factura.emision_local = factura.fecha_emision.astimezone(HORA_DE_PARAGUAY)
        factura.puede_abrir = ve_todas or factura.esta_emitida

    return render(request, 'facturacion/facturas.html', {
        'usuario': request.user,
        'facturas': facturas,
        've_todas': ve_todas,
        'monedas': Moneda.objects.filter(estado=True).order_by('codigo'),
        'clientes': Cliente.objects.order_by('nombre') if ve_todas else [],
        'estados': Factura.ESTADOS,
        'filtros': filtros,
    })


@login_required
@require_GET
def factura_detalle_view(request, pk):
    """Detalle de una factura: emisor, cliente, ítem, montos, tasa, comisión y operación."""
    factura = _factura_accesible(request, pk)
    if factura is None:
        messages.error(request, MENSAJE_SIN_ACCESO)
        return redirect('facturas')
    ve_todas = _ve_todas(request.user)
    return render(request, 'facturacion/factura_detalle.html', {
        'usuario': request.user,
        'factura': factura,
        'transaccion': factura.transaccion,
        'datos': factura.payload,
        'item': factura.payload['gCamItem'][0],
        'emision_local': factura.fecha_emision.astimezone(HORA_DE_PARAGUAY),
        've_todas': ve_todas,
    })


@login_required
@require_GET
def factura_pdf_view(request, pk):
    """Descarga el PDF de una factura emitida."""
    factura = _factura_accesible(request, pk, para_pdf=True)
    if factura is None:
        messages.error(request, MENSAJE_SIN_ACCESO)
        return redirect('facturas')
    respuesta = HttpResponse(generar_pdf(factura), content_type='application/pdf')
    respuesta['Content-Disposition'] = f'attachment; filename="factura-{factura.numero_legal}.pdf"'
    return respuesta
