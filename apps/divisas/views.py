from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .models import TasaCambio, Simulacion
from .serializers import TasaCambioSerializer, SimulacionRequestSerializer


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