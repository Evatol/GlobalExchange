from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ClienteViewSet,
    asignar_rol_view,
    cambiar_password_view,
    cliente_activo,
    cliente_asignar_usuario_view,
    cliente_desasignar_usuario_view,
    cliente_editar_view,
    cliente_toggle_view,
    gestion_clientes_view,
    gestion_roles_view,
    menu_principal_view,
    mi_perfil_view,
    mis_clientes,
    seleccionar_cliente_view,
)

router = DefaultRouter()
router.register('clientes', ClienteViewSet, basename='cliente')

urlpatterns = [
    path('', menu_principal_view, name='menu_principal'),
    path('mi-perfil/', mi_perfil_view, name='mi_perfil'),
    path('mi-perfil/cambiar-password/', cambiar_password_view, name='cambiar_password'),
    path('seleccionar-cliente/', seleccionar_cliente_view, name='seleccionar_cliente'),
    path('mis-clientes/', mis_clientes, name='mis_clientes'),
    path('cliente-activo/', cliente_activo, name='cliente_activo'),
    path('roles/', gestion_roles_view, name='gestion_roles'),
    path('roles/asignar/', asignar_rol_view, name='asignar_rol'),

    # Pantalla propia de gestión de Clientes (HTML), con asociación de
    # usuarios (RF42) incluida. Administrador/analista.
    path('gestion/clientes/', gestion_clientes_view, name='gestion_clientes'),
    path('gestion/clientes/<int:pk>/editar/', cliente_editar_view, name='cliente_editar'),
    path('gestion/clientes/<int:pk>/toggle/', cliente_toggle_view, name='cliente_toggle'),
    path('gestion/clientes/<int:pk>/asignar-usuario/', cliente_asignar_usuario_view, name='cliente_asignar_usuario'),
    path(
        'gestion/clientes/<int:pk>/desasignar-usuario/<int:usuario_id>/',
        cliente_desasignar_usuario_view,
        name='cliente_desasignar_usuario',
    ),
    *router.urls,
]
