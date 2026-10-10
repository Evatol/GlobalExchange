from django.urls import path
from .views import marcar_notificacion_leida, obtener_notificaciones_nuevas

urlpatterns = [
    path('api/notificaciones/nuevas/', obtener_notificaciones_nuevas, name='api_notificaciones_nuevas'),
    path('api/notificaciones/<int:pk>/leida/', marcar_notificacion_leida, name='api_notificacion_leida'),
]