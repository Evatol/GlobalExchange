from decimal import Decimal
from rest_framework import serializers
from .models import Moneda, TasaCambio, Simulacion


class MonedaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Moneda
        fields = ['id', 'codigo', 'nombre', 'simbolo', 'estado']


class TasaCambioSerializer(serializers.ModelSerializer):
    moneda_codigo = serializers.CharField(source='moneda.codigo', read_only=True)
    moneda_nombre = serializers.CharField(source='moneda.nombre', read_only=True)
    moneda_simbolo = serializers.CharField(source='moneda.simbolo', read_only=True)

    class Meta:
        model = TasaCambio
        fields = [
            'id',
            'moneda',
            'moneda_codigo',
            'moneda_nombre',
            'moneda_simbolo',
            'tasa_compra',
            'tasa_venta',
            'fecha_hora',
            'origen',
            'estado',
        ]


class SimulacionRequestSerializer(serializers.Serializer):
    moneda_codigo = serializers.CharField(max_length=10)
    tipo_operacion = serializers.ChoiceField(choices=['compra', 'venta'])
    cantidad = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=Decimal('0.01')
    )

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                'La cantidad debe ser mayor a cero.'
            )
        return value
        #read_only_fields = ['id']
