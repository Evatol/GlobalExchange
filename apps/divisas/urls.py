from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    CotizacionViewSet,
    MonedaViewSet,
    SimuladorConversionView,
    TasasPublicasView,
)

router = DefaultRouter()
router.register('monedas', MonedaViewSet, basename='moneda')
router.register('cotizaciones', CotizacionViewSet, basename='cotizacion')

urlpatterns = [
    path('tasas/', TasasPublicasView.as_view(), name='tasas-publicas'),
    path('simular/', SimuladorConversionView.as_view(), name='simulador-conversion'),
] + router.urls