from django.contrib import admin
from .models import Permiso, Rol, Cliente, Usuario

admin.site.register(Permiso)
admin.site.register(Rol)
admin.site.register(Cliente)
admin.site.register(Usuario)