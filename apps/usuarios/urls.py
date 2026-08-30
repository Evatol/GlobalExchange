from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ClienteViewSet, menu_principal_view

router = DefaultRouter()
router.register('clientes', ClienteViewSet, basename='cliente')

urlpatterns = [
    path('', menu_principal_view, name='menu_principal'),
    *router.urls,
]
