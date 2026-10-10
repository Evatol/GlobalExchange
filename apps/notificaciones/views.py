from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Notificaciones
from apps.usuarios.sesion import usuario_negocio

@login_required
def obtener_notificaciones_nuevas(request):
    """
    Devuelve las notificaciones no leídas del usuario conectado.
    Permite filtrar opcionalmente con ?desde_id=X para traer solo las más recientes.
    """
    usuario = usuario_negocio(request)
    desde_id = request.GET.get('desde_id')

    # Filtrar exclusivamente por el usuario conectado (seguridad estricta)
    qs = Notificaciones.objects.filter(usuario=usuario, leida=False)

    if desde_id and desde_id.isdigit():
        qs = qs.filter(id__gt=int(desde_id))

    qs = qs.order_by('id')  # Orden ascendente para procesarlas en orden

    data = [{
        'id': n.id,
        'titulo': n.titulo,
        'mensaje': n.mensaje,
        'fecha': n.fecha_hora.strftime('%d/%m/%Y %H:%M')
    } for n in qs]

    return JsonResponse({'notificaciones': data}, status=200)