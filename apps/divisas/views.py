from django.shortcuts import render
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Moneda, Simulacion, TasaCambio
from .serializers import (
    MonedaSerializer,
    SimulacionRequestSerializer,
    TasaCambioSerializer,
)


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


class CotizacionViewSet(viewsets.ModelViewSet):
    """CRUD de cotizaciones (E4-26).

    Una "cotización" es una tasa de cambio (``TasaCambio``) de una moneda del
    catálogo (``Moneda``, E4-137): no es un modelo aparte, para no duplicar la
    información que ya usan la consulta pública de tasas (``TasasPublicasView``)
    y el simulador (``SimuladorConversionView``).

    Listar, crear, ver y editar sobre ``/api/divisas/cotizaciones/``. El
    ``DELETE`` no elimina el registro: hace un **borrado lógico**
    (``estado = False``). Para reactivar: ``POST
    /api/divisas/cotizaciones/{id}/activar/``.

    Al crear una cotización activa para una moneda, se desactivan
    automáticamente las demás cotizaciones activas de esa misma moneda: en
    todo momento hay una sola cotización vigente por moneda (la más nueva),
    que es la que ven la consulta pública y el simulador.

    Filtros por querystring: ``?moneda=`` (código, ej. ``USD``) y
    ``?estado=`` (true/false).
    """

    queryset = TasaCambio.objects.all().select_related('moneda').order_by('-fecha_hora')
    serializer_class = TasaCambioSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        moneda = self.request.query_params.get('moneda')
        if moneda:
            queryset = queryset.filter(moneda__codigo__iexact=moneda)
        estado = self.request.query_params.get('estado')
        if estado not in (None, ''):
            queryset = queryset.filter(estado=estado.lower() in ('1', 'true', 'si', 'sí'))
        return queryset

    def perform_create(self, serializer):
        cotizacion = serializer.save()
        if cotizacion.estado:
            TasaCambio.objects.filter(
                moneda=cotizacion.moneda, estado=True
            ).exclude(pk=cotizacion.pk).update(estado=False)

    def destroy(self, request, *args, **kwargs):
        """Borrado lógico: desactiva la cotización en vez de eliminarla."""
        cotizacion = self.get_object()
        cotizacion.estado = False
        cotizacion.save()
        return Response(
            {'detail': f'Cotización de {cotizacion.moneda.codigo} desactivada correctamente.'},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        """Reactiva una cotización y desactiva las demás activas de esa moneda."""
        cotizacion = self.get_object()
        cotizacion.estado = True
        cotizacion.save()
        TasaCambio.objects.filter(
            moneda=cotizacion.moneda, estado=True
        ).exclude(pk=cotizacion.pk).update(estado=False)
        return Response({'detail': f'Cotización de {cotizacion.moneda.codigo} activada.'})


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

        tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)

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


class PantallaPublicaCambiosView(View):
    """Pantalla pública en HTML (RF13, RF20, RF24): cotizaciones del día y
    calculadora de conversión, visible sin haber iniciado sesión.

    No repite la lógica de consulta/cálculo: reutiliza el mismo serializer
    de validación que usa el simulador por API (``SimulacionRequestSerializer``)
    y el mismo manager de ``TasaCambio`` (``objects.activa_para``), para que
    ambas puertas de entrada (esta vista HTML y ``/api/divisas/simular/``)
    calculen siempre igual.
    """

    def get(self, request):
        tasas = TasaCambio.objects.filter(estado=True).select_related('moneda')
        return render(request, 'divisas/publica.html', {'tasas': tasas})

    def post(self, request):
        tasas = TasaCambio.objects.filter(estado=True).select_related('moneda')

        serializer = SimulacionRequestSerializer(data=request.POST)
        resultado = None
        tasa_aplicada = None
        error = None
        moneda_codigo = request.POST.get('moneda_codigo', '')
        tipo_operacion = request.POST.get('tipo_operacion', 'compra')

        if not serializer.is_valid():
            error = ' '.join(
                str(msg) for errores in serializer.errors.values() for msg in errores
            )
        else:
            moneda_codigo = serializer.validated_data['moneda_codigo']
            tipo_operacion = serializer.validated_data['tipo_operacion']
            cantidad = serializer.validated_data['cantidad']

            tasa_obj = TasaCambio.objects.activa_para(moneda_codigo)
            if not tasa_obj:
                error = f"No se encontró una tasa de cambio activa para la moneda '{moneda_codigo}'."
            else:
                tasa_aplicada = (
                    tasa_obj.tasa_compra if tipo_operacion == 'compra' else tasa_obj.tasa_venta
                )
                resultado = cantidad * tasa_aplicada
                Simulacion.objects.create(
                    tipo_operacion=tipo_operacion,
                    cantidad=cantidad,
                    resultado=resultado,
                )

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
