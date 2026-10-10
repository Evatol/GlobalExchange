from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CuentaBancariaViewSet,
    cuenta_cargar_view,
    cuenta_detalle_view,
    cuenta_toggle_view,
    gestion_cuentas_view,
)

router = DefaultRouter()
router.register('cuentas', CuentaBancariaViewSet, basename='cuentabancaria')

urlpatterns = [
    # Pantallas propias del banco simulado (HTML).
    path('gestion/cuentas/', gestion_cuentas_view, name='gestion_cuentas_banco'),
    path('gestion/cuentas/<int:pk>/', cuenta_detalle_view, name='cuenta_banco_detalle'),
    path('gestion/cuentas/<int:pk>/cargar/', cuenta_cargar_view, name='cuenta_banco_cargar'),
    path('gestion/cuentas/<int:pk>/toggle/', cuenta_toggle_view, name='cuenta_banco_toggle'),
] + router.urls
