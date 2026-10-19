from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AsignacionCajeroViewSet,
    SucursalViewSet,
    TerminalViewSet,
    asignacion_cajero_desasignar_view,
    gestion_terminales_view,
    gestion_sucursales_view,
    sucursal_editar_view,
    sucursal_toggle_view,
    terminal_desactivar_view,
    terminal_demo_view,
    terminal_editar_view,
    terminal_operar_view,
)
from .views_billetes import (
    ArqueoViewSet,
    BilleteViewSet,
    CajaViewSet,
    CierreCajaViewSet,
    LimiteStockViewSet,
    MiBalanceAPIView,
    MiCierreAPIView,
    MiInventarioAPIView,
    MovimientoBilleteViewSet,
    OperarPresencialAPIView,
    PrevisualizarOperacionAPIView,
)
from .views_pantallas import (
    billete_toggle_view,
    caja_abrir_view,
    caja_balance_view,
    caja_cerrar_admin_view,
    caja_cerrar_view,
    gestion_cajas_view,
    gestion_denominaciones_view,
    gestion_limites_stock_view,
    mi_caja_view,
    mostrador_view,
)

router = DefaultRouter()
router.register('sucursales', SucursalViewSet, basename='sucursal')
router.register('terminales', TerminalViewSet, basename='terminal')
router.register(
    'asignaciones-cajero', AsignacionCajeroViewSet, basename='asignacioncajero'
)
# RF106: inventario y arqueo de billetes.
router.register('billetes', BilleteViewSet, basename='billete')
router.register('cajas', CajaViewSet, basename='caja')
router.register('arqueos', ArqueoViewSet, basename='arqueo')
# E4-100 / E4-101: historial de cierres y movimientos de billetes.
router.register('cierres', CierreCajaViewSet, basename='cierrecaja')
router.register('movimientos', MovimientoBilleteViewSet, basename='movimientobillete')
# RF107: limites minimo y maximo de stock de billetes por moneda.
router.register('limites-stock', LimiteStockViewSet, basename='limitestock')

urlpatterns = [
    # Pantallas propias de gestión (HTML), en vez de la API navegable de DRF.
    path('gestion/terminales/', gestion_terminales_view, name='gestion_terminales'),
    path(
        'gestion/terminales/<int:pk>/editar/',
        terminal_editar_view,
        name='terminal_editar',
    ),
    path(
        'gestion/terminales/<int:pk>/desactivar/',
        terminal_desactivar_view,
        name='terminal_desactivar',
    ),
    path('autoservicio/<int:pk>/', terminal_demo_view, name='terminal_demo'),
    path(
        'autoservicio/<int:pk>/operar/',
        terminal_operar_view,
        name='terminal_operar',
    ),
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
    path('gestion/limites-stock/', gestion_limites_stock_view, name='gestion_limites_stock'),
    path('gestion/cajas/', gestion_cajas_view, name='gestion_cajas'),
    path('gestion/cajas/<int:pk>/abrir/', caja_abrir_view, name='caja_abrir'),
    path('gestion/cajas/<int:pk>/balance/', caja_balance_view, name='caja_balance'),
    path('gestion/cajas/<int:pk>/cerrar/', caja_cerrar_admin_view, name='caja_cerrar_admin'),
    path('mi-caja/', mi_caja_view, name='mi_caja'),
    path('mi-caja/cerrar/', caja_cerrar_view, name='caja_cerrar'),
    path('mostrador/', mostrador_view, name='mostrador'),

    # RF106: API del cajero.
    path('mi-inventario/', MiInventarioAPIView.as_view(), name='mi_inventario'),
    path('mi-balance/', MiBalanceAPIView.as_view(), name='mi_balance'),
    path('mi-cierre/', MiCierreAPIView.as_view(), name='mi_cierre'),
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