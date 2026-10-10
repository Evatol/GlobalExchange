from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from . import services
from .models import CuentaBancaria, MovimientoBancario


class CuentaBancariaSerializer(serializers.ModelSerializer):
    """Cuenta del banco simulado.

    Al crearla se puede fijar el saldo inicial (una tarjeta arranca con
    toda su línea disponible). Después, número, tipo, titular, saldo y línea
    quedan fijos: el saldo solo se mueve con débitos/créditos registrados
    (``POST .../cargar/`` o el pago de una operación), para que siempre
    coincida con sus movimientos.
    """

    INMUTABLES = ('numero', 'tipo', 'titular_documento', 'saldo', 'linea_credito')

    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    credito_usado = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True
    )

    class Meta:
        model = CuentaBancaria
        fields = [
            'id', 'numero', 'tipo', 'tipo_display', 'entidad',
            'titular_documento', 'titular_nombre',
            'saldo', 'linea_credito', 'credito_usado',
            'estado', 'fecha_creacion',
        ]
        read_only_fields = ['id', 'fecha_creacion']

    def validate(self, attrs):
        if self.instance is not None:
            for campo in self.INMUTABLES:
                if campo in attrs and attrs[campo] != getattr(self.instance, campo):
                    raise serializers.ValidationError({
                        campo: 'No se puede modificar en una cuenta existente.'
                    })
            return attrs

        tipo = attrs.get('tipo')
        linea = attrs.get('linea_credito') or 0
        cuenta = CuentaBancaria(
            tipo=tipo,
            linea_credito=linea,
            saldo=linea if tipo == CuentaBancaria.TIPO_TARJETA_CREDITO else attrs.get('saldo') or 0,
        )
        try:
            cuenta.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs

    def create(self, validated_data):
        validated_data.pop('estado', None)
        return services.abrir_cuenta(**validated_data)


class MovimientoBancarioSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)

    class Meta:
        model = MovimientoBancario
        fields = [
            'id', 'tipo', 'tipo_display', 'monto', 'saldo_resultante',
            'concepto', 'referencia', 'fecha_hora',
        ]
        read_only_fields = fields
