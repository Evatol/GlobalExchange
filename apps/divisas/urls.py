from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CotizacionViewSet,
    MonedaViewSet,
    PantallaPublicaCambiosView,
    SimuladorConversionView,
    TasasPublicasView,
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
] + router.urls
