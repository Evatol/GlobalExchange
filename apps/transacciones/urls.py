from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    CalcularTransaccionAPIView,
    MedioPagoClienteViewSet,
    MetodoPagoViewSet,
    OperarDivisaAPIView,
    TransaccionViewSet,
    WebhookPagoExternoAPIView,
    gestion_medios_pago_view,
    gestion_metodos_pago_view,
    historial_transacciones_view,
    medio_pago_editar_view,
    medio_pago_toggle_view,
    metodo_pago_editar_view,
    metodo_pago_toggle_view,
    operacion_cancelar_view,
    operacion_confirmar_view,
    operacion_detalle_view,
    operacion_pago_externo_view,
    operar_divisa_view,
)

router = DefaultRouter()
router.register('metodos-pago', MetodoPagoViewSet, basename='metodopago')
router.register(
    'medios-pago-cliente', MedioPagoClienteViewSet, basename='mediopagocliente'
)
router.register('transacciones', TransaccionViewSet, basename='transaccion')

urlpatterns = [
    # Pantallas propias de gestión en HTML (RF102, RF17)
    path('gestion/metodos-pago/', gestion_metodos_pago_view, name='gestion_metodos_pago'),
    path('gestion/metodos-pago/<int:pk>/editar/', metodo_pago_editar_view, name='metodo_pago_editar'),
    path('gestion/metodos-pago/<int:pk>/toggle/', metodo_pago_toggle_view, name='metodo_pago_toggle'),
    path('gestion/medios-pago-cliente/', gestion_medios_pago_view, name='gestion_medios_pago'),
    path('gestion/medios-pago-cliente/<int:pk>/editar/', medio_pago_editar_view, name='medio_pago_editar'),
    path('gestion/medios-pago-cliente/<int:pk>/toggle/', medio_pago_toggle_view, name='medio_pago_toggle'),

    # Operaciones de divisas (E4-19/E4-20: Compra, Venta, Cambio)
    path('gestion/operar/', operar_divisa_view, name='operar_divisa'),
    path('gestion/operar/<int:pk>/', operacion_detalle_view, name='operacion_detalle'),
    path('gestion/operar/<int:pk>/confirmar/', operacion_confirmar_view, name='operacion_confirmar'),
    path('gestion/operar/<int:pk>/cancelar/', operacion_cancelar_view, name='operacion_cancelar'),
    # Pago externo (E4-157) y aviso de la pasarela por webhook (E4-158).
    path('gestion/operar/<int:pk>/pago-externo/', operacion_pago_externo_view, name='operacion_pago_externo'),
    path('webhook/pago/', WebhookPagoExternoAPIView.as_view(), name='webhook_pago_externo'),

    # API REST de operaciones y cálculos en tiempo real (E4-144)
    path('operar/', OperarDivisaAPIView.as_view(), name='operar_divisa_api'),
    path('calcular/', CalcularTransaccionAPIView.as_view(), name='calcular_transaccion_api'),

    # Historial de transacciones (E4-104 / E4-36 / RF111)
    path('gestion/historial/', historial_transacciones_view, name='historial_transacciones'),
] + router.urls