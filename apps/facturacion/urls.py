from django.urls import path

from .views import (
    descargar_factura_pdf_view,
    descargar_nota_credito_pdf_view,
    detalle_factura_view,
    lista_facturas_view,
)

urlpatterns = [
    # Pantallas propias (HTML): listado con filtros, detalle y descarga en PDF.
    path('gestion/facturas/', lista_facturas_view, name='lista_facturas'),
    path('gestion/facturas/<int:pk>/', detalle_factura_view, name='detalle_factura'),
    path(
        'gestion/facturas/<int:pk>/pdf/',
        descargar_factura_pdf_view,
        name='descargar_factura_pdf',
    ),
    path(
        'gestion/facturas/<int:pk>/nota-credito/pdf/',
        descargar_nota_credito_pdf_view,
        name='descargar_nota_credito_pdf',
    ),
]