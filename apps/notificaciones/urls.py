from django.urls import path
from .views import obtener_notificaciones_nuevas

urlpatterns = [
    path('api/notificaciones/nuevas/', obtener_notificaciones_nuevas, name='api_notificaciones_nuevas'),
]