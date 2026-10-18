from django.contrib import admin

from .models import Factura, SecuenciaFactura


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ('numero_legal', 'transaccion', 'estado', 'monto', 'proveedor', 'intentos', 'fecha_emision')
    list_filter = ('estado', 'proveedor')
    search_fields = ('cdc', 'transaccion__id', 'transaccion__cliente__nombre')
    readonly_fields = ('payload', 'respuesta')


admin.site.register(SecuenciaFactura)
