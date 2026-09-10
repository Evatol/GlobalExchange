from django.urls import path
from .views import TasasPublicasView, SimuladorConversionView

urlpatterns = [
    path('tasas/', TasasPublicasView.as_view(), name='tasas-publicas'),
    path('simular/', SimuladorConversionView.as_view(), name='simulador-conversion'),
]