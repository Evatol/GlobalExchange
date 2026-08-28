from django.urls import path
from .views import menu_principal_view

urlpatterns = [
    path('', menu_principal_view, name='menu_principal'),]