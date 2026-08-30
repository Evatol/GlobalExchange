from django.contrib import admin

from .models import Cliente, Permiso, Rol, Usuario

admin.site.register(Permiso)
admin.site.register(Rol)
admin.site.register(Usuario)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'documento',
        'tipo',
        'categoria',
        'preferencia_tipo_cambio',
        'estado',
        'fecha_creacion',
    )
    list_filter = ('tipo', 'categoria', 'preferencia_tipo_cambio', 'estado')
    search_fields = ('nombre', 'razon_social', 'documento')
    readonly_fields = ('fecha_creacion',)
    list_editable = ('estado',)
    # La asociación con usuarios (RF42) es la relación inversa del M2M
    # declarado en Usuario.clientes y se administra desde el alta de Usuario.
