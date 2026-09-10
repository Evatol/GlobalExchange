from rest_framework import serializers

from .models import Moneda


class MonedaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Moneda
        fields = ['id', 'codigo', 'nombre', 'simbolo', 'estado']
        read_only_fields = ['id']
