from rest_framework import serializers

from .models import Cliente, Usuario


class UsuarioResumenSerializer(serializers.ModelSerializer):
    """Datos mínimos de un usuario, para listar los asignados a un cliente (RF42)."""

    class Meta:
        model = Usuario
        fields = ['id', 'username', 'nombres', 'apellidos', 'email', 'estado']


class PerfilSerializer(serializers.ModelSerializer):
    """Datos personales que el propio usuario puede actualizar (RF9):
    nombres, apellidos, teléfono y dirección. ``username`` y ``email`` a
    propósito no forman parte de este serializer: quedan bloqueados para
    garantizar la identificación única (RF10)."""

    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    direccion = serializers.CharField(max_length=200, required=False, allow_blank=True)

    class Meta:
        model = Usuario
        fields = ['nombres', 'apellidos', 'telefono', 'direccion']


class ClienteResumenSerializer(serializers.ModelSerializer):
    """Datos mínimos de un cliente, para el selector de cliente activo (RF43)."""

    class Meta:
        model = Cliente
        fields = ['id', 'nombre', 'documento', 'tipo', 'categoria']


class AsignacionUsuarioSerializer(serializers.Serializer):
    """Entrada de las acciones asignar/desasignar usuario de un cliente (RF42)."""

    usuario = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all())


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
