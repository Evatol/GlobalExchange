from django.contrib import admin

from .models import CuentaBancaria, MovimientoBancario


@admin.register(CuentaBancaria)
class CuentaBancariaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'tipo', 'entidad', 'titular_nombre', 'saldo', 'linea_credito', 'estado')
    list_filter = ('tipo', 'estado')
    search_fields = ('numero', 'titular_nombre', 'titular_documento', 'entidad')
    # El saldo solo se mueve por apps.banco.services, para que coincida con
    # los movimientos registrados.
    readonly_fields = ('saldo', 'fecha_creacion')


@admin.register(MovimientoBancario)
class MovimientoBancarioAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'cuenta', 'tipo', 'monto', 'saldo_resultante', 'concepto', 'referencia')
    list_filter = ('tipo',)
    search_fields = ('cuenta__numero', 'referencia', 'concepto')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
