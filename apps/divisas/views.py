from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Moneda
from .serializers import MonedaSerializer


class MonedaViewSet(viewsets.ModelViewSet):
    """CRUD de monedas / divisas (E4-137).

    Listar, crear, ver y editar sobre ``/api/divisas/monedas/``. El ``DELETE`` no
    elimina el registro: hace un **borrado lógico** (``estado = False``). Para
    reactivar una moneda: ``POST /api/divisas/monedas/{id}/activar/``.

    Filtros por querystring: ``?codigo=`` y ``?estado=`` (true/false).
    """

    queryset = Moneda.objects.all().order_by('codigo')
    serializer_class = MonedaSerializer

    FILTROS = ('codigo', 'estado')

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

    def destroy(self, request, *args, **kwargs):
        """Borrado lógico: desactiva la moneda en vez de eliminarla."""
        moneda = self.get_object()
        moneda.desactivar()
        return Response(
            {'detail': f'Moneda {moneda.codigo} desactivada correctamente.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        """Reactiva una moneda previamente desactivada."""
        moneda = self.get_object()
        moneda.activar()
        return Response({'detail': f'Moneda {moneda.codigo} activada.'})
