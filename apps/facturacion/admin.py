from django.contrib import admin

from .models import EventoFactura, Factura, NotaCredito, SecuenciaFactura


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'transaccion', 'estado', 'monto', 'proveedor', 'intentos', 'fecha_emision')
    list_filter = ('estado', 'proveedor')
    search_fields = ('cdc', 'transaccion__id', 'transaccion__cliente__nombre')
    readonly_fields = ('payload', 'respuesta')


@admin.register(NotaCredito)
class NotaCreditoAdmin(admin.ModelAdmin):
    list_display = ('numero', 'factura', 'estado', 'monto', 'proveedor', 'intentos', 'fecha_emision')
    list_filter = ('estado', 'proveedor')
    search_fields = ('cdc', 'factura__transaccion__id')
    readonly_fields = ('payload', 'respuesta')


@admin.register(EventoFactura)
class EventoFacturaAdmin(admin.ModelAdmin):
    """Auditoría de las facturas: solo se consulta (el registro es inalterable)."""

    list_display = ('fecha_hora', 'tipo', 'factura', 'usuario', 'detalle')
    list_filter = ('tipo',)
    search_fields = ('usuario', 'detalle', 'factura__transaccion__id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(SecuenciaFactura)
