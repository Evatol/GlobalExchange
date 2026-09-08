from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import Moneda
from .serializers import MonedaSerializer


class MonedaViewSet(viewsets.ModelViewSet):
    queryset = Moneda.objects.all().order_by('codigo')
    serializer_class = MonedaSerializer

    def destroy(self, request, *args, **kwargs):
        # Borrado lógico: en vez de eliminar el registro, lo desactivamos (idea)
        moneda = self.get_object()
        moneda.desactivar()
        return Response(
            {'detail': f'Moneda {moneda.codigo} desactivada correctamente.'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        moneda = self.get_object()
        moneda.activar()
        return Response({'detail': f'Moneda {moneda.codigo} activada.'})