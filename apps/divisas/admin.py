from django.contrib import admin
from .models import Moneda, TasaCambio, Simulacion, Cotizacion

admin.site.register(Moneda)
admin.site.register(TasaCambio)
admin.site.register(Simulacion)

@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ('moneda', 'tasa_compra', 'tasa_venta', 'fecha_actualizacion')
    search_fields = ('moneda',)
    list_filter = ('fecha_actualizacion',)