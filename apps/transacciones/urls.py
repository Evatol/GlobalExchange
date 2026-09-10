from rest_framework.routers import DefaultRouter

from .views import MedioPagoClienteViewSet, MetodoPagoViewSet

router = DefaultRouter()
router.register('metodos-pago', MetodoPagoViewSet, basename='metodopago')
router.register(
    'medios-pago-cliente', MedioPagoClienteViewSet, basename='mediopagocliente'
)

urlpatterns = router.urls
