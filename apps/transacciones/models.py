from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.usuarios.models import Usuario, Cliente
from apps.divisas.models import Moneda


class MetodoPago(models.Model):
    """Catálogo de métodos de pago admitidos (transferencia, billetera, efectivo…)."""

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


class MedioPagoCliente(models.Model):
    """Medio de pago concreto registrado por un cliente (RF17).

    Un cliente puede tener varios: una cuenta bancaria, una billetera
    electrónica, etc. ``metodo_pago`` es el tipo (del catálogo) e
    ``identificador`` guarda el nº de cuenta / alias de billetera / etc.
    """

    id = models.AutoField(primary_key=True)
    cliente = models.ForeignKey(
        Cliente, on_delete=models.CASCADE, related_name='medios_pago'
    )
    metodo_pago = models.ForeignKey(
        MetodoPago, on_delete=models.PROTECT, related_name='medios_pago_cliente'
    )
    alias = models.CharField(
        max_length=100,
        help_text='Nombre corto para identificarlo (ej. "Cuenta Itaú", "Tigo Money").',
    )
    identificador = models.CharField(
        max_length=100,
        help_text='Nº de cuenta, alias de billetera o dato equivalente.',
    )
    titular = models.CharField(max_length=150, blank=True, default='')
    estado = models.BooleanField('activo', default=True)
    fecha_creacion = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['cliente', 'alias']
        constraints = [
            models.UniqueConstraint(
                fields=['cliente', 'metodo_pago', 'identificador'],
                name='medio_pago_cliente_unico',
            )
        ]

    def clean(self):
        if self.metodo_pago_id and not self.metodo_pago.estado:
            raise ValidationError(
                {'metodo_pago': 'El método de pago está desactivado en el catálogo.'}
            )

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return f'{self.cliente.nombre} - {self.alias}'


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