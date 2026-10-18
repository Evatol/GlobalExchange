from django.urls import path

from .views import pagar_view, stripe_retorno_view, stripe_webhook_view

urlpatterns = [
    path('pagar/<str:referencia>/', pagar_view, name='pasarela_pagar'),
    # Stripe: a donde vuelve el cliente después de pagar, y los avisos de Stripe.
    path('stripe/retorno/', stripe_retorno_view, name='pasarela_stripe_retorno'),
    path('stripe/webhook/', stripe_webhook_view, name='pasarela_stripe_webhook'),
]
