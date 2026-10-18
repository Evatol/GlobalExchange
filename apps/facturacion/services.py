"""apps/facturacion/services.py - consulta y descarga de facturas (Sprint 5).

Reúne las reglas de acceso, los filtros del listado y la generación del PDF,
para que las pantallas queden finas y cada regla se pueda probar por separado.
"""
import io
from xml.sax.saxutils import escape

from django.conf import settings
from django.db.models import Q
from django.utils.dateparse import parse_date

from apps.usuarios import sesion
from apps.usuarios.permissions import ADMINISTRADOR, ANALISTA, tiene_rol

from .models import Factura, NotaCredito


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

def puede_ver_todas(user):
    """True si el usuario consulta las facturas de todos los clientes, en solo
    lectura: administrador o analista."""
    return tiene_rol(user, (ADMINISTRADOR, ANALISTA))


def facturas_visibles(request):
    """Facturas que el usuario ve en el listado.

    Administrador y analista ven todas. Cualquier otro usuario ve solo las del
    cliente activo de su sesión (RF43), igual que en el historial.
    """
    base = Factura.objects.select_related(
        'transaccion__cliente', 'transaccion__moneda', 'transaccion__moneda_destino'
    ).order_by('-fecha', '-id')
    if puede_ver_todas(request.user):
        return base
    cliente = sesion.get_cliente_activo(request)
    if cliente is None:
        return base.none()
    return base.filter(transaccion__cliente=cliente)


def motivo_de_denegacion(request, factura, descarga=False):
    """Devuelve ``None`` si el usuario puede ver (o descargar) la factura; si
    no, el mensaje de error que se le muestra.

    Un usuario común solo accede a facturas emitidas de su cliente activo (y a las
    que después se anularon: siguen existiendo, con su nota de crédito).
    Administrador y analista consultan cualquiera, pero el PDF solo existe
    para facturas emitidas o anuladas.
    """
    if puede_ver_todas(request.user):
        if descarga and not factura.es_consultable:
            return 'Solo se pueden descargar facturas emitidas.'
        return None

    cliente = sesion.get_cliente_activo(request)
    if cliente is None:
        return 'No tenés un cliente activo seleccionado.'
    if factura.transaccion.cliente_id != cliente.pk:
        return 'No tenés acceso a esta factura: pertenece a otro cliente.'
    if not factura.es_consultable:
        return (
            'Esta factura todavía no fue emitida, por lo que no se puede '
            'consultar ni descargar.'
        )
    return None


# ---------------------------------------------------------------------------
# Filtros del listado
# ---------------------------------------------------------------------------

def _entero(valor):
    """Entero a partir de texto, o ``None`` si no es un número razonable."""
    valor = (valor or '').strip()
    if valor.isascii() and valor.isdigit() and len(valor) <= 18:
        return int(valor)
    return None


def _fecha(valor):
    """Fecha a partir de ``AAAA-MM-DD``, o ``None`` si no es válida."""
    try:
        return parse_date(valor)
    except ValueError:
        return None


def _id_desde_numero(texto):
    """Número de la factura a partir de lo escrito (``001-001-0000042`` o ``42``): es el
    correlativo, o el id en las facturas que no tienen correlativo."""
    return _entero((texto or '').strip().split('-')[-1])


def filtrar_facturas(queryset, params):
    """Aplica los filtros del listado a ``queryset``.

    Lee de ``params`` (la query string): ``fecha_desde``, ``fecha_hasta``
    (``AAAA-MM-DD``), ``numero``, ``moneda`` (id, de la divisa que entrega o
    recibe el cliente) y ``estado``. Un filtro con un valor inválido no se
    aplica y se informa. Devuelve ``(queryset, errores)``.
    """
    errores = []

    for campo, lookup, etiqueta in (
        ('fecha_desde', 'fecha__gte', 'Desde'),
        ('fecha_hasta', 'fecha__lte', 'Hasta'),
    ):
        valor = params.get(campo, '').strip()
        if not valor:
            continue
        fecha = _fecha(valor)
        if fecha is None:
            errores.append(f'La fecha "{etiqueta}" no es válida.')
        else:
            queryset = queryset.filter(**{lookup: fecha})

    numero = params.get('numero', '').strip()
    if numero:
        factura_id = _id_desde_numero(numero)
        if factura_id is None:
            errores.append('El número de factura no es válido.')
        else:
            queryset = queryset.filter(
                Q(correlativo=factura_id) | Q(correlativo__isnull=True, pk=factura_id)
            )

    moneda = params.get('moneda', '').strip()
    if moneda:
        moneda_id = _entero(moneda)
        if moneda_id is None:
            errores.append('La moneda no es válida.')
        else:
            queryset = queryset.filter(
                Q(transaccion__moneda_id=moneda_id)
                | Q(transaccion__moneda_destino_id=moneda_id)
            )

    estado = params.get('estado', '').strip().upper()
    if estado:
        queryset = queryset.filter(estado=estado)

    return queryset, errores


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _emisor(factura=None):
    """Datos fiscales del emisor. En una factura que emitió el sistema salen del
    documento que se envió (``payload``), para que el PDF coincida con lo que recibió
    SIFEN. Si no (los datos de demostración), los valores por defecto son de
    demostración y se cambian definiendo ``EMPRESA_RAZON_SOCIAL``, ``EMPRESA_RUC``,
    ``EMPRESA_DIRECCION`` y ``EMPRESA_TIMBRADO`` en la configuración."""
    datos = factura.payload if factura is not None else {}
    if datos.get('dRucEm'):
        return {
            'razon_social': datos['dNomEmi'],
            'ruc': f"{datos['dRucEm']}-{datos['dDVEmi']}",
            'direccion': f"{datos['dDirEmi']} {datos['dNumCas']}, {datos['dDesCiuEmi']}",
            'timbrado': datos['dNumTim'],
        }
    return {
        'razon_social': getattr(settings, 'EMPRESA_RAZON_SOCIAL', 'GlobalExchange S.A.'),
        'ruc': getattr(settings, 'EMPRESA_RUC', '80000000-1'),
        'direccion': getattr(settings, 'EMPRESA_DIRECCION', 'Asunción, Paraguay'),
        'timbrado': getattr(settings, 'EMPRESA_TIMBRADO', '12345678'),
    }


def _fmt(valor, decimales=2):
    """Importe con punto de miles y coma decimal (``1.234.567,89``)."""
    texto = f'{valor:,.{decimales}f}'
    return texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def generar_pdf(factura):
    """Genera el PDF de una factura y devuelve su contenido en bytes.

    Incluye los datos fiscales del emisor, el número y la fecha de la factura,
    los datos del cliente y el detalle de la operación: cantidad, tasa
    aplicada, subtotal, comisión, total y la transacción asociada.
    """
    # reportlab se importa acá, como en el historial, para que importar el
    # módulo (por ejemplo al compilar la documentación) no lo requiera.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    t = factura.transaccion
    cliente = t.cliente
    emisor = _emisor(factura)
    nota = NotaCredito.objects.filter(factura=factura).first()
    estilos = getSampleStyleSheet()
    normal = estilos['Normal']

    def parrafo(texto, estilo=normal):
        # Paragraph interpreta marcado: se escapa el texto que viene de la base.
        return Paragraph(escape(str(texto)), estilo)

    def tabla(filas):
        celdas = [
            [Paragraph(f'<b>{escape(etiqueta)}</b>', normal), parrafo(valor)]
            for etiqueta, valor in filas
        ]
        resultado = Table(celdas, colWidths=[6 * cm, 11 * cm])
        resultado.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        return resultado

    factura_filas = [
        ('Factura N°', factura.numero),
        ('Fecha de emisión', factura.fecha.strftime('%d/%m/%Y')),
        ('Estado', factura.estado),
        ('Transacción asociada', f'#{t.id} - {t.get_tipo_display()} ({t.modalidad})'),
    ]
    if factura.cdc:
        factura_filas.append(('CDC', factura.cdc))
    if factura.estado_sifen:
        factura_filas.append(('Estado en SIFEN', factura.estado_sifen))
    cliente_filas = [
        ('Nombre / razón social', cliente.razon_social or cliente.nombre),
        ('Documento / RUC', cliente.documento),
    ]
    operacion_filas = [
        ('Operación', t.get_tipo_display()),
        ('Moneda', t.moneda.codigo),
        ('Cantidad', _fmt(t.cantidad)),
        ('Tasa de cambio aplicada', _fmt(t.tasa_cambio)),
        ('Subtotal (Gs.)', _fmt(t.subtotal)),
        ('Comisión', f'{_fmt(t.comision_porcentaje)} % = {_fmt(t.monto_comision)} Gs.'),
        ('Total de la operación (Gs.)', _fmt(t.monto_total)),
        ('Método de pago', t.metodo_pago.nombre),
    ]
    if t.moneda_destino_id:
        operacion_filas += [
            ('Divisa recibida', t.moneda_destino.codigo),
            ('Tasa de la divisa recibida', _fmt(t.tasa_cambio_destino)),
            ('Cantidad recibida', _fmt(t.cantidad_destino)),
        ]
    operacion_filas.append(('Monto facturado (Gs.)', _fmt(factura.monto)))

    elementos = [
        parrafo(emisor['razon_social'], estilos['Title']),
        parrafo(f"RUC: {emisor['ruc']}  |  Timbrado N° {emisor['timbrado']}"),
        parrafo(emisor['direccion']),
        *(
            [parrafo(
                'DOCUMENTO DE PRUEBA generado por el simulador: sin validez tributaria.',
                estilos['Italic'],
            )]
            if factura.proveedor == 'SIMULADO' else []
        ),
        *(
            [parrafo(
                f'FACTURA ANULADA' + (
                    f' por la nota de crédito N° {nota.numero}.' if nota is not None else '.'
                ),
                estilos['Heading3'],
            )]
            if factura.estado == Factura.ANULADA else []
        ),
        Spacer(1, 0.5 * cm),
        parrafo('Factura', estilos['Heading2']),
        tabla(factura_filas),
        Spacer(1, 0.4 * cm),
        parrafo('Cliente', estilos['Heading3']),
        tabla(cliente_filas),
        Spacer(1, 0.4 * cm),
        parrafo('Detalle de la operación', estilos['Heading3']),
        tabla(operacion_filas),
        Spacer(1, 0.6 * cm),
        parrafo(
            'Documento generado por GlobalExchange. Sistema desarrollado con '
            'fines académicos.',
            estilos['Italic'],
        ),
    ]

    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f'Factura {factura.numero}',
        author=emisor['razon_social'],
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    documento.build(elementos)
    return buffer.getvalue()


def generar_pdf_nota_credito(nota):
    """Genera el PDF de una nota de crédito y devuelve su contenido en bytes: el
    emisor y el cliente del documento enviado, su número y CDC, y la factura que anula."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    factura = nota.factura
    cliente = factura.transaccion.cliente
    emisor = _emisor(nota)
    estilos = getSampleStyleSheet()
    normal = estilos['Normal']

    def parrafo(texto, estilo=normal):
        return Paragraph(escape(str(texto)), estilo)

    def tabla(filas):
        celdas = [
            [Paragraph(f'<b>{escape(etiqueta)}</b>', normal), parrafo(valor)]
            for etiqueta, valor in filas
        ]
        resultado = Table(celdas, colWidths=[6 * cm, 11 * cm])
        resultado.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        return resultado

    nota_filas = [
        ('Nota de crédito N°', nota.numero),
        ('Fecha de emisión', nota.fecha_emision.strftime('%d/%m/%Y') if nota.fecha_emision else ''),
        ('Estado', nota.estado),
        ('Motivo', nota.motivo),
        ('Factura que anula', factura.numero),
        ('Monto acreditado (Gs.)', _fmt(nota.monto)),
    ]
    if nota.cdc:
        nota_filas.append(('CDC', nota.cdc))
    if nota.estado_sifen:
        nota_filas.append(('Estado en SIFEN', nota.estado_sifen))

    elementos = [
        parrafo(emisor['razon_social'], estilos['Title']),
        parrafo(f"RUC: {emisor['ruc']}  |  Timbrado N° {emisor['timbrado']}"),
        parrafo(emisor['direccion']),
        *(
            [parrafo(
                'DOCUMENTO DE PRUEBA generado por el simulador: sin validez tributaria.',
                estilos['Italic'],
            )]
            if nota.proveedor == 'SIMULADO' else []
        ),
        Spacer(1, 0.5 * cm),
        parrafo('Nota de crédito', estilos['Heading2']),
        tabla(nota_filas),
        Spacer(1, 0.4 * cm),
        parrafo('Cliente', estilos['Heading3']),
        tabla([
            ('Nombre / razón social', cliente.razon_social or cliente.nombre),
            ('Documento / RUC', cliente.documento),
        ]),
        Spacer(1, 0.6 * cm),
        parrafo(
            'Documento generado por GlobalExchange. Sistema desarrollado con '
            'fines académicos.',
            estilos['Italic'],
        ),
    ]
    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, title=f'Nota de crédito {nota.numero}',
        author=emisor['razon_social'], leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    ).build(elementos)
    return buffer.getvalue()
