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
    # RF106: cajero responsable de la caja (stock de billetes por caja/cajero).
    cajero = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, null=True, blank=True,
        related_name='cajas',
    )
    fecha_apertura = models.DateTimeField(null=True, blank=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    saldo_inicial = models.DecimalField(max_digits=15, decimal_places=2)
    saldo_actual = models.DecimalField(max_digits=15, decimal_places=2)
    estado = models.CharField(max_length=30, default='CERRADA')

    class Meta:
        constraints = [
            # Un cajero no puede tener dos cajas abiertas a la vez.
            models.UniqueConstraint(
                fields=['cajero'],
                condition=models.Q(estado='ABIERTA'),
                name='un_cajero_una_caja_abierta',
            )
        ]

    def clean(self):
        # El cajero debe estar asignado y activo en la sucursal de la caja.
        if self.cajero_id and self.sucursal_id:
            asignado = AsignacionCajero.objects.filter(
                sucursal_id=self.sucursal_id,
                usuario_id=self.cajero_id,
                estado=True,
            ).exists()
            if not asignado:
                raise ValidationError(
                    {'cajero': 'El cajero no está asignado a la sucursal de esta caja.'}
                )

    def abrir(self):
        # La apertura de RF106 (fecha, carga inicial de billetes) pasa por
        # apps.caja.services.abrir_caja; este método queda por compatibilidad.
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
    """Catálogo de denominaciones por moneda (lo carga el administrador).

    El stock físico ya no vive acá sino en ``StockBillete``, por caja.
    """

    id = models.AutoField(primary_key=True)
    denominacion = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='billetes')
    estado = models.BooleanField(default=True)

    class Meta:
        ordering = ['moneda__codigo', 'denominacion']
        constraints = [
            models.UniqueConstraint(
                fields=['moneda', 'denominacion'],
                name='billete_moneda_denominacion_unica',
            )
        ]

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return f'{self.moneda.codigo} {self.denominacion}'


class StockBillete(models.Model):
    """Cantidad de billetes de una denominación en una caja."""

    id = models.AutoField(primary_key=True)
    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name='stock_billetes')
    billete = models.ForeignKey(Billete, on_delete=models.PROTECT, related_name='stocks')
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['caja', 'billete'], name='stock_billete_unico')
        ]

    @property
    def subtotal(self):
        return self.billete.denominacion * self.cantidad

    def __str__(self):
        return f'{self.caja} - {self.billete}: {self.cantidad}'


class MovimientoBillete(models.Model):
    """Entrada o salida de billetes de una caja. Lo crea
    ``apps.caja.services.registrar_movimientos_billetes``, que también
    actualiza el stock. La carga inicial de la apertura es una ENTRADA sin
    transacción."""

    TIPOS = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
    ]

    id = models.AutoField(primary_key=True)
    caja = models.ForeignKey(Caja, on_delete=models.CASCADE, related_name='movimientos_billetes')
    billete = models.ForeignKey(Billete, on_delete=models.PROTECT, related_name='movimientos')
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='movimientos_billetes'
    )
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


class Arqueo(models.Model):
    """Arqueo de caja (RF106): lo que el cajero contó contra lo que el
    sistema esperaba, por caja y moneda. No ajusta el stock."""

    id = models.AutoField(primary_key=True)
    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name='arqueos')
    cajero = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='arqueos')
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='arqueos')
    fecha_hora = models.DateTimeField(auto_now_add=True)
    total_esperado = models.DecimalField(max_digits=15, decimal_places=2)
    total_contado = models.DecimalField(max_digits=15, decimal_places=2)
    diferencia = models.DecimalField(max_digits=15, decimal_places=2)  # contado - esperado

    class Meta:
        ordering = ['-fecha_hora']

    def __str__(self):
        return f'Arqueo #{self.id} - {self.caja} ({self.moneda.codigo})'


class DetalleArqueo(models.Model):
    id = models.AutoField(primary_key=True)
    arqueo = models.ForeignKey(Arqueo, on_delete=models.CASCADE, related_name='detalles')
    billete = models.ForeignKey(Billete, on_delete=models.PROTECT, related_name='detalles_arqueo')
    cantidad_esperada = models.PositiveIntegerField()
    cantidad_contada = models.PositiveIntegerField()

    @property
    def diferencia(self):
        return self.cantidad_contada - self.cantidad_esperada