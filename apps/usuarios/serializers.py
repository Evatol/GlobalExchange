from rest_framework import serializers

from .models import Cliente, Usuario


class ClienteSerializer(serializers.ModelSerializer):
    """Serializa el CRUD de clientes (E4-125), incluida la asociación
    con uno o más usuarios (RF42)."""

    usuarios = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Usuario.objects.all(),
    )

    class Meta:
        model = Cliente
        fields = [
            'id',
            'nombre',
            'razon_social',
            'documento',
            'tipo',
            'categoria',
            'estado',
            'limite_compra',
            'limite_venta',
            'frecuencia_transacciones',
            'preferencia_tipo_cambio',
            'fecha_creacion',
            'usuarios',
        ]
        read_only_fields = ['id', 'fecha_creacion']

    def validate_limite_compra(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                'El límite de compra no puede ser negativo.'
            )
        return value

    def validate_limite_venta(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                'El límite de venta no puede ser negativo.'
            )
        return value

    def validate(self, attrs):
        tipo = attrs.get('tipo', getattr(self.instance, 'tipo', None))
        razon_social = attrs.get(
            'razon_social', getattr(self.instance, 'razon_social', '')
        )
        if tipo == Cliente.TIPO_CHOICES[1][0] and not razon_social:
            raise serializers.ValidationError(
                {'razon_social': 'La razón social es obligatoria para personas jurídicas.'}
            )
        return attrs
