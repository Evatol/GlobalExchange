from django.contrib import admin
from .models import Moneda, TasaCambio, Simulacion

admin.site.register(Moneda)
admin.site.register(TasaCambio)
admin.site.register(Simulacion)