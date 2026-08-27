from django.contrib import admin
from .models import Cuenta, Sucursal, Caja, Billete, MovimientoBillete

admin.site.register(Cuenta)
admin.site.register(Sucursal)
admin.site.register(Caja)
admin.site.register(Billete)
admin.site.register(MovimientoBillete)