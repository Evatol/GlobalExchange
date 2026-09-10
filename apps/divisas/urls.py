from rest_framework.routers import DefaultRouter

from .views import MonedaViewSet

router = DefaultRouter()
router.register('monedas', MonedaViewSet, basename='moneda')

urlpatterns = router.urls
