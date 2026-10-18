"""PDF de una factura electrónica (representación gráfica del documento).

Se genera acá, con los datos con los que la factura se envió (``Factura.payload``) y los de
la operación (tasa y comisión), así que es igual para el simulador y para Factura Segura
y no depende de que el proveedor tenga el PDF listo. Solo se genera para facturas
``EMITIDA`` (lo controla la vista).
"""

import io
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.banco.services import formatear_guaranies

from .proveedores import NOMBRE_SIMULADO
from .services import HORA_DE_PARAGUAY

_ESTILOS = getSampleStyleSheet()
_NORMAL = ParagraphStyle('normal', parent=_ESTILOS['Normal'], fontSize=9, leading=12)
_CHICO = ParagraphStyle('chico', parent=_NORMAL, fontSize=8, textColor=colors.grey)
_TITULO = ParagraphStyle('titulo', parent=_ESTILOS['Title'], fontSize=18, spaceAfter=4)
_AVISO = ParagraphStyle(
    'aviso', parent=_NORMAL, textColor=colors.HexColor('#9C2B2B'), alignment=1, fontSize=9,
)


def _p(texto, estilo=_NORMAL):
    return Paragraph(escape(str(texto)), estilo)


def _bloque(titulo, lineas):
    """Una celda con un título en negrita y una línea de texto por dato."""
    texto = f'<b>{escape(titulo)}</b><br/>' + '<br/>'.join(escape(str(l)) for l in lineas if l)
    return Paragraph(texto, _NORMAL)


def _documento_del_receptor(payload):
    if payload.get('dRucRec'):
        return f"RUC {payload['dRucRec']}-{payload['dDVRec']}"
    return f"Documento {payload.get('dNumIDRec', '')}"


def generar_pdf(factura):
    """Los bytes del PDF de la factura."""
    payload = factura.payload
    transaccion = factura.transaccion
    item = payload['gCamItem'][0]
    emision = factura.fecha_emision.astimezone(HORA_DE_PARAGUAY).strftime('%d/%m/%Y %H:%M')
    total = Decimal(item['dPUniProSer']) * Decimal(item['dCantProSer'])
    medio = transaccion.medio_pago.alias if transaccion.medio_pago else transaccion.metodo_pago.nombre

    contenido = [_p('FACTURA ELECTRÓNICA', _TITULO)]
    if factura.proveedor == NOMBRE_SIMULADO:
        contenido += [
            _p('DOCUMENTO DE PRUEBA generado por el simulador: sin validez tributaria.', _AVISO),
            Spacer(1, 0.2 * cm),
        ]
    contenido.append(Spacer(1, 0.3 * cm))

    cabecera = Table([[
        _bloque(payload['dNomEmi'], [
            f"RUC {payload['dRucEm']}-{payload['dDVEmi']}",
            f"{payload['dDirEmi']} {payload['dNumCas']}, {payload['dDesCiuEmi']}",
            f"Tel. {payload['dTelEmi']}",
            payload['dEmailE'],
            payload['gActEco'][0]['dDesActEco'],
        ]),
        _bloque(f'Factura N° {factura.numero_legal}', [
            f"Timbrado N° {payload['dNumTim']} (vigente desde {payload['dFeIniT']})",
            f'Fecha de emisión: {emision}',
            'Condición: Contado',
            f'CDC: {factura.cdc}',
        ]),
    ]], colWidths=[8.5 * cm, 8.5 * cm])
    cabecera.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    contenido += [cabecera, Spacer(1, 0.4 * cm)]

    contenido += [
        _bloque('Cliente', [
            payload['dNomRec'], _documento_del_receptor(payload), payload['dEmailRec'],
        ]),
        Spacer(1, 0.4 * cm),
    ]

    detalle = Table(
        [
            ['Descripción', 'Cant.', 'Precio unitario', 'Exentas'],
            [
                _p(item['dDesProSer']), item['dCantProSer'],
                formatear_guaranies(Decimal(item['dPUniProSer'])), formatear_guaranies(total),
            ],
            ['', '', 'TOTAL A PAGAR', formatear_guaranies(total)],
        ],
        colWidths=[8 * cm, 1.8 * cm, 3.6 * cm, 3.6 * cm],
    )
    detalle.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E6E9E')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (2, 2), (-1, 2), 'Helvetica-Bold'),
    ]))
    contenido += [detalle, Spacer(1, 0.5 * cm)]

    contenido += [
        _bloque('Detalle de la operación', [
            f'Operación #{transaccion.pk} ({transaccion.get_tipo_display()}) · Medio de pago: {medio}',
            payload['dInfAdic'],
            f'Subtotal: {formatear_guaranies(transaccion.subtotal)} · '
            f'Comisión ({transaccion.comision_porcentaje}%): '
            f'{formatear_guaranies(transaccion.monto_comision)} · '
            f'Total: {formatear_guaranies(transaccion.monto_total)}',
        ]),
        Spacer(1, 0.4 * cm),
        _p(f'Estado en SIFEN: {factura.estado_sifen or factura.get_estado_display()}', _CHICO),
        _p('Representación gráfica de la factura electrónica. Verificá su autenticidad con el '
           'CDC en el portal e-Kuatia de la DNIT.', _CHICO),
    ]

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
        bottomMargin=2 * cm, title=f'Factura {factura.numero_legal}',
    ).build(contenido)
    return buffer.getvalue()
