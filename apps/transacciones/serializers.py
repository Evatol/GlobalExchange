from rest_framework import serializers

from .models import MedioPagoCliente, MetodoPago, Transaccion


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
        # Sin el validador automático de la restricción única del modelo: se
        # adelantaba a validate() y mostraba "Los campos cliente, metodo_pago,
        # identificador deben formar un conjunto único.". El duplicado lo
        # controla validate() con un mensaje claro, y la base lo sigue
        # garantizando con la UniqueConstraint.
        validators = []

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

        # Salvo el efectivo, tiene que ser una cuenta del banco a nombre del
        # cliente: si no, cualquiera podría pagar con la tarjeta de otro.
        error_banco = MedioPagoCliente(
            cliente=cliente, metodo_pago=metodo_pago, identificador=identificador,
        ).validar_cuenta_banco()
        if error_banco:
            raise serializers.ValidationError({'identificador': error_banco})
        return attrs


class TransaccionSerializer(serializers.ModelSerializer):
    """Historial de transacciones, de solo consulta (RF111 / E4-104)."""
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    moneda_codigo = serializers.CharField(source='moneda.codigo', read_only=True)
    metodo_pago_nombre = serializers.CharField(source='metodo_pago.nombre', read_only=True)
    medio_pago_alias = serializers.CharField(
        source='medio_pago.alias', read_only=True, default=None
    )
    moneda_destino_codigo = serializers.CharField(
        source='moneda_destino.codigo', read_only=True, default=None
    )

    class Meta:
        model = Transaccion
        fields = [
            'id', 'fecha_hora', 'tipo',
            'cliente', 'cliente_nombre',
            'moneda', 'moneda_codigo',
            'metodo_pago', 'metodo_pago_nombre',
            'medio_pago', 'medio_pago_alias',
            'cantidad', 'tasa_cambio', 'monto_total',
            'moneda_destino', 'moneda_destino_codigo',
            'tasa_cambio_destino', 'cantidad_destino',
            'estado', 'observacion', 'modalidad',
        ]
        read_only_fields = fields