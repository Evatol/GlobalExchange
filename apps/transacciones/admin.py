from django.contrib import admin

from .models import MedioPagoCliente, MetodoPago, Transaccion

admin.site.register(MetodoPago)
admin.site.register(Transaccion)


@admin.register(MedioPagoCliente)
class MedioPagoClienteAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'alias', 'metodo_pago', 'identificador', 'estado')
    list_filter = ('estado', 'metodo_pago')
    search_fields = ('alias', 'identificador', 'titular', 'cliente__nombre')
    readonly_fields = ('fecha_creacion',)
