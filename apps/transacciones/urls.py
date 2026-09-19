from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    MedioPagoClienteViewSet,
    MetodoPagoViewSet,
    gestion_medios_pago_view,
    gestion_metodos_pago_view,
    medio_pago_editar_view,
    medio_pago_toggle_view,
    metodo_pago_editar_view,
    metodo_pago_toggle_view,
)

router = DefaultRouter()
router.register('metodos-pago', MetodoPagoViewSet, basename='metodopago')
router.register(
    'medios-pago-cliente', MedioPagoClienteViewSet, basename='mediopagocliente'
)

urlpatterns = [
    # Pantallas propias de gestión (HTML), en vez de la API navegable de DRF.
    path('gestion/metodos-pago/', gestion_metodos_pago_view, name='gestion_metodos_pago'),
    path('gestion/metodos-pago/<int:pk>/editar/', metodo_pago_editar_view, name='metodo_pago_editar'),
    path('gestion/metodos-pago/<int:pk>/toggle/', metodo_pago_toggle_view, name='metodo_pago_toggle'),
    path('gestion/medios-pago-cliente/', gestion_medios_pago_view, name='gestion_medios_pago'),
    path('gestion/medios-pago-cliente/<int:pk>/editar/', medio_pago_editar_view, name='medio_pago_editar'),
    path('gestion/medios-pago-cliente/<int:pk>/toggle/', medio_pago_toggle_view, name='medio_pago_toggle'),
] + router.urls
