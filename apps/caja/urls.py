from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AsignacionCajeroViewSet,
    SucursalViewSet,
    asignacion_cajero_desasignar_view,
    gestion_sucursales_view,
    sucursal_editar_view,
    sucursal_toggle_view,
)

router = DefaultRouter()
router.register('sucursales', SucursalViewSet, basename='sucursal')
router.register(
    'asignaciones-cajero', AsignacionCajeroViewSet, basename='asignacioncajero'
)

urlpatterns = [
    # Pantallas propias de gestión (HTML), en vez de la API navegable de DRF.
    path('gestion/sucursales/', gestion_sucursales_view, name='gestion_sucursales'),
    path('gestion/sucursales/<int:pk>/editar/', sucursal_editar_view, name='sucursal_editar'),
    path('gestion/sucursales/<int:pk>/toggle/', sucursal_toggle_view, name='sucursal_toggle'),
    path(
        'gestion/asignaciones-cajero/<int:pk>/desasignar/',
        asignacion_cajero_desasignar_view,
        name='asignacion_cajero_desasignar',
    ),
] + router.urls