from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .models import TasaCambio, Simulacion
from .serializers import TasaCambioSerializer, SimulacionRequestSerializer
from django.shortcuts import render
from django.views import View
from .models import TasaCambio, Simulacion
from decimal import Decimal

class PantallaPublicaCambiosView(View):
    """
    Vista web tradicional (HTML) que muestra la pantalla pública de la casa de cambios,
    las cotizaciones activas y el simulador de conversión.
    """
    def get(self, request):
        # Obtener tasas activas para la tabla
        tasas = TasaCambio.objects.filter(estado=True).select_related('moneda')
        
        context = {
            'tasas': tasas,
        }
        return render(request, 'divisas/publica.html', context)

    def post(self, request):
        # Manejo simple del simulador desde el formulario web
        tasas = TasaCambio.objects.filter(estado=True).select_related('moneda')
        moneda_codigo = request.POST.get('moneda_codigo')
        tipo_operacion = request.POST.get('tipo_operacion', 'compra')
        
        resultado = None
        tasa_aplicada = None
        error = None

        try:
            cantidad = Decimal(request.POST.get('cantidad', '0'))
            if cantidad <= 0:
                raise ValueError("La cantidad debe ser mayor a cero.")
            
            tasa_obj = tasas.filter(moneda__codigo__iexact=moneda_codigo).first()
            if tasa_obj:
                tasa_aplicada = tasa_obj.tasa_compra if tipo_operacion == 'compra' else tasa_obj.tasa_venta
                resultado = cantidad * tasa_aplicada
                
                # Opcional: guardar simulación
                Simulacion.objects.create(
                    tipo_operacion=tipo_operacion,
                    cantidad=cantidad,
                    resultado=resultado
                )
            else:
                error = "Seleccione una moneda válida."
        except Exception as e:
            error = str(e)

        context = {
            'tasas': tasas,
            'resultado': resultado,
            'tasa_aplicada': tasa_aplicada,
            'cantidad_ingresada': request.POST.get('cantidad'),
            'moneda_seleccionada': moneda_codigo,
            'tipo_operacion': tipo_operacion,
            'error': error,
        }
        return render(request, 'divisas/publica.html', context)

class TasasPublicasView(APIView):
    """
    Vista pública para consultar las tasas de cambio activas (pantalla pública).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        # Obtiene la lista de tasas activas
        tasas = TasaCambio.objects.filter(estado=True).select_related('moneda')
        serializer = TasaCambioSerializer(tasas, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SimuladorConversionView(APIView):
    """
    Vista pública para simular conversiones de divisa (compra / venta).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SimulacionRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        moneda_codigo = serializer.validated_data['moneda_codigo']
        tipo_operacion = serializer.validated_data['tipo_operacion']
        cantidad = serializer.validated_data['cantidad']

        # Buscar la tasa activa más reciente para la moneda
        tasa_obj = (
            TasaCambio.objects.filter(
                moneda__codigo__iexact=moneda_codigo, estado=True
            )
            .order_by('-fecha_hora')
            .first()
        )

        if not tasa_obj:
            return Response(
                {
                    "error": f"No se encontró una tasa de cambio activa para la moneda '{moneda_codigo}'."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Seleccionar la tasa correspondiente según si es compra o venta
        if tipo_operacion == 'compra':
            tasa_aplicada = tasa_obj.tasa_compra
        else:
            tasa_aplicada = tasa_obj.tasa_venta

        # Utilizar el modelo Simulacion para guardar y calcular
        simulacion = Simulacion(
            tipo_operacion=tipo_operacion,
            cantidad=cantidad,
            resultado=cantidad * tasa_aplicada,
        )
        simulacion.save()

        return Response(
            {
                "moneda": tasa_obj.moneda.codigo,
                "simbolo": tasa_obj.moneda.simbolo,
                "tipo_operacion": tipo_operacion,
                "cantidad": cantidad,
                "tasa_aplicada": tasa_aplicada,
                "resultado": simulacion.resultado,
                "fecha_hora": simulacion.fecha_hora,
            },
            status=status.HTTP_200_OK,
        )
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
