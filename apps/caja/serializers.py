from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AsignacionCajero, Sucursal


class SucursalSerializer(serializers.ModelSerializer):
    """Sucursal presencial (RF105 / E4-98)."""

    # default=True explícito: un formulario HTML (multipart) que no manda el
    # campo lo interpreta como False y la sucursal se crearía inactiva.
    estado = serializers.BooleanField(default=True)

    class Meta:
        model = Sucursal
        fields = ['id', 'nombre', 'direccion', 'estado']
        read_only_fields = ['id']


class AsignacionCajeroSerializer(serializers.ModelSerializer):
    """Asignación de un cajero a una sucursal (RF105 / E4-98).

    Las reglas (rol cajero y máximo de 2 por sucursal) viven en
    ``AsignacionCajero.clean`` y se reutilizan acá, para que valgan igual
    desde la API y desde el admin.
    """

    # Mismo motivo que en SucursalSerializer: si no viene, la asignación
    # nace activa y cuenta para el máximo de cajeros.
    estado = serializers.BooleanField(default=True)
    sucursal_nombre = serializers.CharField(source='sucursal.nombre', read_only=True)
    usuario_username = serializers.CharField(source='usuario.username', read_only=True)

    class Meta:
        model = AsignacionCajero
        fields = [
            'id', 'sucursal', 'sucursal_nombre',
            'usuario', 'usuario_username', 'estado', 'fecha_asignacion',
        ]
        read_only_fields = ['id', 'fecha_asignacion']

    def validate(self, attrs):
        actual = self.instance
        candidata = AsignacionCajero(
            pk=getattr(actual, 'pk', None),
            sucursal=attrs.get('sucursal', getattr(actual, 'sucursal', None)),
            usuario=attrs.get('usuario', getattr(actual, 'usuario', None)),
            estado=attrs.get('estado', getattr(actual, 'estado', True)),
        )
        try:
            candidata.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs