from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from . import services
from .models import AsignacionCajero, Billete, Sucursal, Terminal


class SucursalSerializer(serializers.ModelSerializer):
    """Sucursal presencial (RF105 / E4-98)."""

    # default=True explícito: un formulario HTML (multipart) que no manda el
    # campo lo interpreta como False y la sucursal se crearía inactiva.
    estado = serializers.BooleanField(default=True)

    class Meta:
        model = Sucursal
        fields = ['id', 'nombre', 'direccion', 'estado']
        read_only_fields = ['id']


class TerminalSerializer(serializers.ModelSerializer):
    """Terminal de autoservicio con caja e inventario inicial propios."""

    sucursal_nombre = serializers.CharField(source='sucursal.nombre', read_only=True)
    caja_id = serializers.IntegerField(read_only=True)
    stock_inicial = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        write_only=True,
        required=False,
        default=dict,
    )

    class Meta:
        model = Terminal
        fields = [
            'id', 'nombre', 'sucursal', 'sucursal_nombre', 'estado', 'caja_id',
            'stock_inicial',
        ]
        read_only_fields = ['id', 'caja_id']

    def validate(self, attrs):
        actual = self.instance
        sucursal = attrs.get('sucursal', getattr(actual, 'sucursal', None))
        estado = attrs.get('estado', getattr(actual, 'estado', Terminal.ACTIVA))
        if actual is not None and 'stock_inicial' in self.initial_data:
            raise serializers.ValidationError({
                'stock_inicial': 'El stock inicial solo se define al crear la terminal.'
            })
        stock_inicial = attrs.get('stock_inicial', {})
        if actual is None and stock_inicial:
            try:
                billete_ids = {int(billete_id) for billete_id in stock_inicial}
            except (TypeError, ValueError):
                raise serializers.ValidationError({
                    'stock_inicial': 'Los identificadores de denominación deben ser números.'
                })
            activos = set(
                Billete.objects.filter(pk__in=billete_ids, estado=True)
                .values_list('pk', flat=True)
            )
            if activos != billete_ids:
                raise serializers.ValidationError({
                    'stock_inicial': 'El stock solo puede cargarse en denominaciones activas.'
                })
        if sucursal is not None and not sucursal.estado and (
            actual is None or sucursal != actual.sucursal or estado == Terminal.ACTIVA
        ):
            raise serializers.ValidationError({
                'sucursal': 'La sucursal debe estar activa para asignar o activar una terminal.'
            })
        return attrs

    def create(self, validated_data):
        """Crea la terminal junto con la caja y el stock inicial."""
        stock_inicial = validated_data.pop('stock_inicial', {})
        try:
            return services.crear_terminal(
                stock_inicial=stock_inicial, **validated_data
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(
                exc, 'message_dict'
            ) else exc.messages)

    def update(self, instance, validated_data):
        """Actualiza la terminal y mantiene su caja en la misma sucursal."""
        validated_data.pop('stock_inicial', None)
        try:
            return services.actualizar_terminal(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(
                exc, 'message_dict'
            ) else exc.messages)


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