from django.urls import path

from .views import pagar_view

urlpatterns = [
    path('pagar/<str:referencia>/', pagar_view, name='pasarela_pagar'),
]
