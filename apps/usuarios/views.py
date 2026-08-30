from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from rest_framework import viewsets

from .models import Cliente
from .serializers import ClienteSerializer


@login_required
def menu_principal_view(request):
    """
    Vista del Menú Principal conectada al estado de autenticación.
    """
    context = {
        'usuario': request.user,
    }
    return render(request, 'usuarios/menu_principal.html', context)


class ClienteViewSet(viewsets.ModelViewSet):
    """CRUD completo de clientes (E4-125).

    Expone listar, crear, ver detalle, editar y eliminar sobre ``/api/usuarios/clientes/``.
    Permite filtrar por ``tipo``, ``categoria``, ``estado`` y
    ``preferencia_tipo_cambio`` vía querystring para la segmentación de datos.
    """

    queryset = Cliente.objects.all().prefetch_related('usuarios')
    serializer_class = ClienteSerializer

    FILTROS = ('tipo', 'categoria', 'estado', 'preferencia_tipo_cambio')

    def get_queryset(self):
        queryset = super().get_queryset()
        for campo in self.FILTROS:
            valor = self.request.query_params.get(campo)
            if valor in (None, ''):
                continue
            if campo == 'estado':
                valor = valor.lower() in ('1', 'true', 'si', 'sí')
            queryset = queryset.filter(**{campo: valor})
        return queryset
