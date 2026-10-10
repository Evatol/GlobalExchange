from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from apps.usuarios.models import Cliente, Usuario
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

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

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

class AsignacionCajero(models.Model):
    """Vincula un usuario cajero con una sucursal presencial (RF105, RF109).

    Reglas (E4-98): solo se asignan usuarios con rol ``cajero`` y una
    sucursal admite como máximo ``MAX_CAJEROS`` cajeros activos en paralelo.
    Desasignar es un borrado lógico (``estado=False``); reasignar es
    reactivar la fila existente con ``activar()``, que vuelve a validar.
    """

    MAX_CAJEROS = 2

    id = models.AutoField(primary_key=True)
    sucursal = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, related_name='asignaciones_cajero'
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name='asignaciones_cajero'
    )
    estado = models.BooleanField('activa', default=True)
    fecha_asignacion = models.DateField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sucursal', 'usuario'], name='asignacion_cajero_unica'
            )
        ]

    def clean(self):
        # Import local para no cargar DRF al registrar los modelos.
        from apps.usuarios.permissions import usuario_tiene_rol_cajero

        errores = {}
        if self.usuario_id and not usuario_tiene_rol_cajero(self.usuario):
            errores['usuario'] = 'Solo se pueden asignar usuarios con rol cajero.'
        if self.sucursal_id and self.estado:
            activos = AsignacionCajero.objects.filter(
                sucursal_id=self.sucursal_id, estado=True
            ).exclude(pk=self.pk)
            if activos.count() >= self.MAX_CAJEROS:
                errores['sucursal'] = (
                    f'La sucursal ya tiene {self.MAX_CAJEROS} cajeros asignados; '
                    'no se puede asignar un tercero.'
                )
        if errores:
            raise ValidationError(errores)

    def activar(self):
        self.estado = True
        self.full_clean()
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return f'{self.usuario} - {self.sucursal}'