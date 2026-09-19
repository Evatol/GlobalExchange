from rest_framework import serializers

from .models import MedioPagoCliente, MetodoPago


class MetodoPagoSerializer(serializers.ModelSerializer):
    """Catálogo de métodos de pago admitidos."""

    class Meta:
        model = MetodoPago
        fields = ['id', 'nombre', 'tipo', 'estado']
        read_only_fields = ['id']


class MedioPagoClienteSerializer(serializers.ModelSerializer):
    """Medio de pago de un cliente (RF17)."""

    metodo_pago_nombre = serializers.CharField(
        source='metodo_pago.nombre', read_only=True
    )
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)

    class Meta:
        model = MedioPagoCliente
        fields = [
            'id',
            'cliente',
            'cliente_nombre',
            'metodo_pago',
            'metodo_pago_nombre',
            'alias',
            'identificador',
            'titular',
            'estado',
            'fecha_creacion',
        ]
        read_only_fields = ['id', 'fecha_creacion']

    def validate_metodo_pago(self, value):
        if not value.estado:
            raise serializers.ValidationError(
                'El método de pago está desactivado en el catálogo.'
            )
        return value

    def validate(self, attrs):
        cliente = attrs.get('cliente') or getattr(self.instance, 'cliente', None)
        metodo_pago = attrs.get('metodo_pago') or getattr(
            self.instance, 'metodo_pago', None
        )
        identificador = attrs.get(
            'identificador', getattr(self.instance, 'identificador', None)
        )
        existe = (
            MedioPagoCliente.objects.filter(
                cliente=cliente,
                metodo_pago=metodo_pago,
                identificador=identificador,
            )
            .exclude(pk=getattr(self.instance, 'pk', None))
            .exists()
        )
        if existe:
            raise serializers.ValidationError(
                'Ese cliente ya tiene registrado ese medio de pago.'
            )
        return attrs

from .models import Transaccion


class TransaccionSerializer(serializers.ModelSerializer):
    """Historial de transacciones, de solo consulta (RF111 / E4-104)."""
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    moneda_codigo = serializers.CharField(source='moneda.codigo', read_only=True)
    metodo_pago_nombre = serializers.CharField(source='metodo_pago.nombre', read_only=True)

    class Meta:
        model = Transaccion
        fields = [
            'id', 'fecha_hora', 'tipo',
            'cliente', 'cliente_nombre',
            'moneda', 'moneda_codigo',
            'metodo_pago', 'metodo_pago_nombre',
            'cantidad', 'tasa_cambio', 'monto_total',
            'estado', 'modalidad',
        ]
        read_only_fields = fields