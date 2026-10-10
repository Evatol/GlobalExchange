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
from .views_billetes import (
    ArqueoViewSet,
    BilleteViewSet,
    CajaViewSet,
    MiInventarioAPIView,
    OperarPresencialAPIView,
    PrevisualizarOperacionAPIView,
)
from .views_pantallas import (
    billete_toggle_view,
    caja_abrir_view,
    gestion_cajas_view,
    gestion_denominaciones_view,
    mi_caja_view,
)

router = DefaultRouter()
router.register('sucursales', SucursalViewSet, basename='sucursal')
router.register(
    'asignaciones-cajero', AsignacionCajeroViewSet, basename='asignacioncajero'
)
# RF106: inventario y arqueo de billetes.
router.register('billetes', BilleteViewSet, basename='billete')
router.register('cajas', CajaViewSet, basename='caja')
router.register('arqueos', ArqueoViewSet, basename='arqueo')

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

    # RF106: pantallas del administrador y del cajero.
    path('gestion/denominaciones/', gestion_denominaciones_view, name='gestion_denominaciones'),
    path('gestion/denominaciones/<int:pk>/toggle/', billete_toggle_view, name='billete_toggle'),
    path('gestion/cajas/', gestion_cajas_view, name='gestion_cajas'),
    path('gestion/cajas/<int:pk>/abrir/', caja_abrir_view, name='caja_abrir'),
    path('mi-caja/', mi_caja_view, name='mi_caja'),

    # RF106: API del cajero.
    path('mi-inventario/', MiInventarioAPIView.as_view(), name='mi_inventario'),
    path(
        'operaciones-presenciales/calcular/',
        PrevisualizarOperacionAPIView.as_view(),
        name='operacion_presencial_calcular',
    ),
    path(
        'operaciones-presenciales/',
        OperarPresencialAPIView.as_view(),
        name='operacion_presencial',
    ),
] + router.urls