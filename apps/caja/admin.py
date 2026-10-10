from django.contrib import admin

from .models import (
    Arqueo, AsignacionCajero, Billete, Caja, Cuenta, DetalleArqueo,
    MovimientoBillete, StockBillete, Sucursal,
)

for modelo in (
    Cuenta, Sucursal, Caja, Billete, StockBillete, MovimientoBillete,
    AsignacionCajero, Arqueo, DetalleArqueo,
):
    admin.site.register(modelo)