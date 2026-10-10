from django.shortcuts import render

# Create your views here.
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
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


@login_required
@require_POST
def marcar_notificacion_leida(request, pk):
    """Marca como leída una notificación del usuario conectado.

    El aviso se muestra hasta que el usuario lo cierra: al cerrarlo, la pantalla
    llama a este endpoint y deja de volver a aparecer. Solo se puede marcar una
    notificación propia: la de otro usuario responde 404, igual que una que no existe.
    """
    notificacion = Notificaciones.objects.filter(pk=pk, usuario=usuario_negocio(request)).first()
    if notificacion is None:
        return JsonResponse({'detail': 'No existe esa notificación.'}, status=404)
    notificacion.marcar_leida()
    return JsonResponse({'id': notificacion.pk, 'leida': True})
