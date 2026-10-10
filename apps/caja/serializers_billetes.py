"""apps/caja/serializers_billetes.py - serializers de RF106 (billetes, cajas,
operación presencial y arqueo)."""
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.divisas.models import Moneda

from .models import (
    Arqueo, Billete, Caja, DetalleArqueo, MovimientoBillete, StockBillete,
)

TIPOS_OPERACION = ('COMPRA', 'VENTA', 'CAMBIO')


class BilleteSerializer(serializers.ModelSerializer):
    """Denominaciones por moneda (las carga el administrador)."""

    # default=True explícito, igual que en SucursalSerializer: un formulario
    # HTML sin el checkbox marcado no manda el campo.
    estado = serializers.BooleanField(default=True)
    moneda_codigo = serializers.CharField(source='moneda.codigo', read_only=True)

    class Meta:
        model = Billete
        fields = ['id', 'moneda', 'moneda_codigo', 'denominacion', 'estado']
        read_only_fields = ['id']
        # La unicidad se controla en validate() con un mensaje claro; la base
        # la sigue garantizando con la UniqueConstraint.
        validators = []

    def validate_denominacion(self, value):
        if value <= 0:
            raise serializers.ValidationError('La denominación debe ser mayor a cero.')
        return value

    def validate(self, attrs):
        actual = self.instance
        moneda = attrs.get('moneda', getattr(actual, 'moneda', None))
        denominacion = attrs.get('denominacion', getattr(actual, 'denominacion', None))

        repetida = Billete.objects.filter(
            moneda=moneda, denominacion=denominacion
        ).exclude(pk=getattr(actual, 'pk', None)).exists()
        if repetida:
            raise serializers.ValidationError('Esa denominación ya existe para esa moneda.')

        # Cambiar el valor o la moneda de una denominación con historial
        # corrompería el stock y los movimientos: se desactiva y se crea otra.
        if actual is not None and (moneda != actual.moneda or denominacion != actual.denominacion):
            tiene_historial = (
                StockBillete.objects.filter(billete=actual).exists()
                or MovimientoBillete.objects.filter(billete=actual).exists()
            )
            if tiene_historial:
                raise serializers.ValidationError(
                    'No se puede cambiar una denominación que ya tiene stock o '
                    'movimientos: desactivala y creá otra.'
                )
        return attrs


class CajaSerializer(serializers.ModelSerializer):
    """Caja de una sucursal con su cajero responsable. El estado y las
    fechas los maneja la apertura (``POST .../abrir/``)."""

    sucursal_nombre = serializers.CharField(source='sucursal.nombre', read_only=True)
    cajero_username = serializers.CharField(
        source='cajero.username', read_only=True, default=None
    )
    # RF106 no usa estos importes; quedan en 0 si no se mandan.
    saldo_inicial = serializers.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    saldo_actual = serializers.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )

    class Meta:
        model = Caja
        fields = [
            'id', 'sucursal', 'sucursal_nombre', 'cajero', 'cajero_username',
            'estado', 'fecha_apertura', 'fecha_cierre',
            'saldo_inicial', 'saldo_actual',
        ]
        read_only_fields = ['id', 'estado', 'fecha_apertura', 'fecha_cierre']
        validators = []

    def validate(self, attrs):
        actual = self.instance
        sucursal = attrs.get('sucursal', getattr(actual, 'sucursal', None))
        cajero = attrs.get('cajero', getattr(actual, 'cajero', None))

        if actual is not None and actual.estado == 'ABIERTA':
            if cajero != actual.cajero:
                raise serializers.ValidationError(
                    {'cajero': 'No se puede cambiar el cajero de una caja abierta.'}
                )
            if sucursal != actual.sucursal:
                raise serializers.ValidationError(
                    {'sucursal': 'No se puede cambiar la sucursal de una caja abierta.'}
                )

        # Misma regla que el modelo: el cajero debe estar asignado a la sucursal.
        try:
            Caja(sucursal=sucursal, cajero=cajero).clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return attrs


# ---- Entradas (lo que manda el cliente de la API) -------------------------

def _cantidades():
    """{billete_id: cantidad}, con cantidades enteras >= 0."""
    return serializers.DictField(
        child=serializers.IntegerField(min_value=0), required=False, default=dict
    )


class AbrirCajaSerializer(serializers.Serializer):
    carga_inicial = _cantidades()


class OperacionPreviewSerializer(serializers.Serializer):
    documento = serializers.CharField()
    tipo = serializers.ChoiceField(choices=TIPOS_OPERACION)
    moneda_codigo = serializers.CharField()
    cantidad = serializers.DecimalField(
        max_digits=15, decimal_places=2, min_value=Decimal('0.01')
    )
    moneda_destino_codigo = serializers.CharField(required=False, allow_blank=True)


class OperacionPresencialSerializer(OperacionPreviewSerializer):
    recibidos = _cantidades()
    entregados = _cantidades()


class ArqueoEntradaSerializer(serializers.Serializer):
    moneda = serializers.PrimaryKeyRelatedField(queryset=Moneda.objects.filter(estado=True))
    contados = _cantidades()


# ---- Salidas --------------------------------------------------------------

class DetalleArqueoSerializer(serializers.ModelSerializer):
    denominacion = serializers.DecimalField(
        source='billete.denominacion', max_digits=10, decimal_places=2, read_only=True
    )
    diferencia = serializers.IntegerField(read_only=True)

    class Meta:
        model = DetalleArqueo
        fields = [
            'billete', 'denominacion',
            'cantidad_esperada', 'cantidad_contada', 'diferencia',
        ]
        read_only_fields = fields


class ArqueoSerializer(serializers.ModelSerializer):
    moneda_codigo = serializers.CharField(source='moneda.codigo', read_only=True)
    cajero_username = serializers.CharField(source='cajero.username', read_only=True)
    detalles = DetalleArqueoSerializer(many=True, read_only=True)

    class Meta:
        model = Arqueo
        fields = [
            'id', 'caja', 'cajero', 'cajero_username', 'moneda', 'moneda_codigo',
            'fecha_hora', 'total_esperado', 'total_contado', 'diferencia', 'detalles',
        ]
        read_only_fields = fields