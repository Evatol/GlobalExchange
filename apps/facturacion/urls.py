from django.urls import path

from .views import factura_detalle_view, factura_pdf_view, facturas_view

urlpatterns = [
    # Consulta y descarga de facturas electrónicas (RF33)
    path('gestion/facturas/', facturas_view, name='facturas'),
    path('gestion/facturas/<int:pk>/', factura_detalle_view, name='factura_detalle'),
    path('gestion/facturas/<int:pk>/pdf/', factura_pdf_view, name='factura_pdf'),
]
