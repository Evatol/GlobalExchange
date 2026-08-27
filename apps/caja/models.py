from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.usuarios.models import Cliente
from apps.divisas.models import Moneda
from apps.transacciones.models import Transaccion


class Cuenta(models.Model):
    id = models.AutoField(primary_key=True)
    cliente = models.OneToOneField(Cliente, on_delete=models.CASCADE, related_name='cuenta')
    saldo = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    estado = models.BooleanField(default=True)
    fecha_creacion = models.DateField(auto_now_add=True)

    def consultar_saldo(self):
        return self.saldo

    def depositar(self, monto):
        if monto <= 0:
            raise ValidationError('El monto debe ser mayor a cero.')
        self.saldo += monto
        self.save()

    def retirar(self, monto):
        if monto <= 0:
            raise ValidationError('El monto debe ser mayor a cero.')
        if monto > self.saldo:
            raise ValidationError('Saldo insuficiente.')
        self.saldo -= monto
        self.save()

    def cambiar_estado(self, estado):
        self.estado = estado
        self.save()

    def __str__(self):
        return f'Cuenta {self.id}'


class Sucursal(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=250)
    estado = models.BooleanField(default=True)

    def consultar_cajas(self):
        return self.cajas.all()

    def __str__(self):
        return self.nombre


class Caja(models.Model):
    id = models.AutoField(primary_key=True)
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='cajas')
    fecha_apertura = models.DateTimeField(null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    saldo_inicial = models.DecimalField(max_digits=15, decimal_places=2)
    saldo_actual = models.DecimalField(max_digits=15, decimal_places=2)
    estado = models.CharField(max_length=30, default='CERRADA')

    def abrir(self):
        self.estado = 'ABIERTA'
        self.save()

    def cerrar(self):
        self.estado = 'CERRADA'
        self.save()

    def calcular_saldo(self):
        return self.saldo_actual

    def __str__(self):
        return f'Caja #{self.id}'


class Billete(models.Model):
    id = models.AutoField(primary_key=True)
    denominacion = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='billetes')
    cantidad = models.IntegerField(default=0)

    def aumentar_cantidad(self, cantidad):
        if cantidad <= 0:
            raise ValidationError('La cantidad debe ser positiva.')
        self.cantidad += cantidad
        self.save()

    def disminuir_cantidad(self, cantidad):
        if cantidad > self.cantidad:
            raise ValidationError('Stock insuficiente.')
        self.cantidad -= cantidad
        self.save()

    def consultar_cantidad(self):
        return self.cantidad

    def verificar_stock(self):
        return self.cantidad > 0

    def __str__(self):
        return f'{self.moneda.codigo} {self.denominacion}'


class MovimientoBillete(models.Model):
    TIPOS = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
    ]

    id = models.AutoField(primary_key=True)
    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name='movimientos_billetes')
    billete = models.ForeignKey(Billete, on_delete=models.PROTECT, related_name='movimientos')
    transaccion = models.ForeignKey(
        Transaccion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimientos_billetes'
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    cantidad = models.IntegerField()
    fecha_hora = models.DateTimeField(auto_now_add=True)

    def validar_movimiento(self):
        return self.cantidad > 0

    def registrar_entrada(self):
        if not self.validar_movimiento():
            raise ValidationError('Movimiento inválido.')
        self.billete.aumentar_cantidad(self.cantidad)

    def registrar_salida(self):
        if not self.validar_movimiento():
            raise ValidationError('Movimiento inválido.')
        self.billete.disminuir_cantidad(self.cantidad)

    def __str__(self):
        return f'Movimiento #{self.id}'