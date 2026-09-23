from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CotizacionViewSet,
    MonedaViewSet,
    PantallaPublicaCambiosView,
    SimuladorConversionView,
    TasasPublicasView,
    cotizacion_editar_view,
    cotizacion_toggle_view,
    gestion_cotizaciones_view,
    gestion_monedas_view,
    moneda_editar_view,
    moneda_toggle_view,
)

router = DefaultRouter()
router.register('monedas', MonedaViewSet, basename='moneda')
router.register('cotizaciones', CotizacionViewSet, basename='cotizacion')

urlpatterns = [
    # Pantalla pública principal (HTML): cotizaciones del día + calculadora,
    # visible sin haber iniciado sesión (RF13, RF20, RF24).
    path('', PantallaPublicaCambiosView.as_view(), name='pantalla-publica'),

    # Endpoints de API (JSON)
    path('tasas/', TasasPublicasView.as_view(), name='tasas-publicas'),
    path('simular/', SimuladorConversionView.as_view(), name='simulador-conversion'),

    # Pantallas propias de gestión (HTML), en vez de la API navegable de DRF.
    # Solo administrador/analista (RF21/RF22).
    path('gestion/monedas/', gestion_monedas_view, name='gestion_monedas'),
    path('gestion/monedas/<int:pk>/editar/', moneda_editar_view, name='moneda_editar'),
    path('gestion/monedas/<int:pk>/toggle/', moneda_toggle_view, name='moneda_toggle'),
    path('gestion/cotizaciones/', gestion_cotizaciones_view, name='gestion_cotizaciones'),
    path('gestion/cotizaciones/<int:pk>/editar/', cotizacion_editar_view, name='cotizacion_editar'),
    path('gestion/cotizaciones/<int:pk>/toggle/', cotizacion_toggle_view, name='cotizacion_toggle'),
] + router.urls
