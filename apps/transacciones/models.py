from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.usuarios.models import Usuario, Cliente
from apps.divisas.models import Moneda


class MetodoPago(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50)
    estado = models.BooleanField(default=True)

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def validar(self):
        return self.estado

    def __str__(self):
        return self.nombre


class Transaccion(models.Model):
    TIPOS = [
        ('COMPRA', 'Compra'),
        ('VENTA', 'Venta'),
    ]

    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('EXITOSA', 'Exitosa'),
        ('FALLIDA', 'Fallida'),
        ('CANCELADA', 'Cancelada'),
    ]

    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='transacciones')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='transacciones')
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='transacciones')
    metodo_pago = models.ForeignKey(MetodoPago, on_delete=models.PROTECT, related_name='transacciones')
    tipo = models.CharField(max_length=20, choices=TIPOS)
    cantidad = models.DecimalField(max_digits=15, decimal_places=2)
    tasa_cambio = models.DecimalField(max_digits=15, decimal_places=6)
    monto_total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    fecha_hora = models.DateTimeField(auto_now_add=True)
    modalidad = models.CharField(max_length=30)

    def calcular_monto_total(self):
        self.monto_total = self.cantidad * self.tasa_cambio
        return self.monto_total

    def validar(self):
        return self.cantidad > 0 and self.tasa_cambio > 0 and self.metodo_pago.estado

    def confirmar(self):
        if not self.validar():
            raise ValidationError('La transacción no es válida.')
        
        # Obtenemos la tasa de cambio vigente desde el modelo TasaCambio asociado
        tasa_obj = self.moneda.tasas.filter(estado=True).order_by('-fecha_hora').first()
        if not tasa_obj:
            raise ValidationError('No hay una tasa de cambio vigente para esta moneda.')
        
        tasa_actual = tasa_obj.tasa_compra if self.tipo == 'COMPRA' else tasa_obj.tasa_venta
        
        # Verificamos si la tasa cambió desde que se creó la transacción
        if self.tasa_cambio != tasa_actual:
            self.estado = 'CANCELADA'
            self.save()
            raise ValidationError('La transacción ha sido cancelada porque la tasa de cambio ha sufrido modificaciones.')

        self.calcular_monto_total()
        self.estado = 'EXITOSA'
        self.save()

    def cancelar(self):
        if self.estado == 'EXITOSA':
            raise ValidationError('No se puede cancelar una transacción exitosa.')
        self.estado = 'CANCELADA'
        self.save()

    def cambiar_estado(self, estado):
        if estado not in dict(self.ESTADOS):
            raise ValidationError('Estado de transacción inválido.')
        self.estado = estado
        self.save()

    def __str__(self):
        return f'{self.tipo} #{self.id}'