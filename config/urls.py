from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    # Redirige la raíz directamente a la pantalla pública HTML de divisas
    path('', RedirectView.as_view(url='/api/divisas/', permanent=False)),
    path('admin/', admin.site.urls),

    # Módulos de la API
    path('api/usuarios/', include('apps.usuarios.urls')),
    path('api/proyectos/', include('apps.proyectos.urls')),
    path('api/caja/', include('apps.caja.urls')),
    path('api/divisas/', include('apps.divisas.urls')),
    path('api/transacciones/', include('apps.transacciones.urls')),
    path('api/facturacion/', include('apps.facturacion.urls')),
    path('api/notificaciones/', include('apps.notificaciones.urls')),
    path('api/reportes/', include('apps.reportes.urls')),

    # Autenticación Keycloak / OpenID Connect
    path('oidc/', include('mozilla_django_oidc.urls')),
]