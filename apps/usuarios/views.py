from django.shortcuts import render
from django.contrib.auth.decorators import login_required

@login_required
def menu_principal_view(request):
    """
    Vista del Menú Principal conectada al estado de autenticación.
    """
    context = {
        'usuario': request.user,
    }
    return render(request, 'usuarios/menu_principal.html', context)