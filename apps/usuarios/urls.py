from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ClienteViewSet,
    asignar_rol_view,
    cliente_activo,
    gestion_roles_view,
    menu_principal_view,
    mis_clientes,
    seleccionar_cliente_view,
)

router = DefaultRouter()
router.register('clientes', ClienteViewSet, basename='cliente')

urlpatterns = [
    path('', menu_principal_view, name='menu_principal'),
    path('seleccionar-cliente/', seleccionar_cliente_view, name='seleccionar_cliente'),
    path('mis-clientes/', mis_clientes, name='mis_clientes'),
    path('cliente-activo/', cliente_activo, name='cliente_activo'),
    path('roles/', gestion_roles_view, name='gestion_roles'),
    path('roles/asignar/', asignar_rol_view, name='asignar_rol'),
    *router.urls,
]
