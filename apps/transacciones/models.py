from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db import models, transaction
from django.core.exceptions import ValidationError
from apps.banco import services as banco
from apps.banco.models import CuentaBancaria
from apps.usuarios.models import Usuario, Cliente
from apps.divisas.models import Moneda


def _a_guaranies(monto):
    """Redondea un importe a 2 decimales, que es la precisión con la que se
    guarda en la base (``decimal_places=2``).
    """
    return monto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class MetodoPago(models.Model):
    """Catálogo de métodos de pago admitidos (transferencia, billetera, efectivo…)."""

    TIPO_EFECTIVO = 'EFECTIVO'
    TIPO_TRANSFERENCIA = 'TRANSFERENCIA'
    TIPO_BILLETERA = 'BILLETERA'
    TIPO_TARJETA_CREDITO = 'TARJETA_CREDITO'
    TIPO_CHOICES = [
        (TIPO_EFECTIVO, 'Efectivo'),
        (TIPO_TRANSFERENCIA, 'Transferencia bancaria'),
        (TIPO_BILLETERA, 'Billetera electrónica'),
        (TIPO_TARJETA_CREDITO, 'Tarjeta de crédito'),
    ]

    CUENTA_BANCO_POR_TIPO = {
        TIPO_TRANSFERENCIA: CuentaBancaria.TIPO_CUENTA,
        TIPO_BILLETERA: CuentaBancaria.TIPO_BILLETERA,
        TIPO_TARJETA_CREDITO: CuentaBancaria.TIPO_TARJETA_CREDITO,
    }

    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, choices=TIPO_CHOICES)
    estado = models.BooleanField(default=True)

    @property
    def usa_banco(self):
        return self.tipo in self.CUENTA_BANCO_POR_TIPO

    @property
    def tipo_cuenta_banco(self):
        return self.CUENTA_BANCO_POR_TIPO.get(self.tipo)

    @property
    def permite_venta(self):
        return self.tipo != self.TIPO_TARJETA_CREDITO

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
    """Medio de pago concreto registrado por un cliente (RF17)."""

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
        error = self.validar_cuenta_banco()
        if error:
            raise ValidationError({'identificador': error})

    def validar_cuenta_banco(self):
        if not self.metodo_pago_id or not self.cliente_id or not self.metodo_pago.usa_banco:
            return None
        return banco.verificar_titular(
            self.identificador, self.metodo_pago.tipo_cuenta_banco, self.cliente.documento
        )

    @property
    def cuenta_banco(self):
        if not self.metodo_pago.usa_banco:
            return None
        return banco.buscar_cuenta(self.identificador)

    @property
    def disponible(self):
        cuenta = self.cuenta_banco
        return cuenta.saldo if cuenta is not None else None

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return f'{self.cliente.nombre} - {self.alias}'


class Transaccion(models.Model):
    """Operación de un cliente: compra o venta de divisas contra guaraníes,
    o cambio de una divisa por otra.
    """

    TIPOS = [
        ('COMPRA', 'Compra'),
        ('VENTA', 'Venta'),
        ('CAMBIO', 'Cambio entre divisas'),
    ]

    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('PENDIENTE_PAGO', 'Pendiente de Pago Externo'),
        ('PAGADO', 'Pagado'),
        ('EXITOSA', 'Exitosa'),
        ('FALLIDA', 'Fallida'),
        ('CANCELADA', 'Cancelada'),
    ]

    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='transacciones')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='transacciones')
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='transacciones')
    metodo_pago = models.ForeignKey(MetodoPago, on_delete=models.PROTECT, related_name='transacciones')
    medio_pago = models.ForeignKey(
        MedioPagoCliente, on_delete=models.PROTECT, null=True, blank=True,
        related_name='transacciones',
    )
    tipo = models.CharField(max_length=20, choices=TIPOS)
    cantidad = models.DecimalField(max_digits=15, decimal_places=2)
    tasa_cambio = models.DecimalField(max_digits=15, decimal_places=6)
    comision_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.50'))
    monto_comision = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    monto_total = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    fecha_hora = models.DateTimeField(auto_now_add=True)
    modalidad = models.CharField(max_length=30, default='DIGITAL')

    # Campos de integración externa (Tickets E4-157 / E4-158)
    referencia_pago_externo = models.CharField(
        max_length=100, blank=True, null=True, unique=True,
        help_text="ID o Token devuelto por la pasarela de pago externa"
    )
    proveedor_pago = models.CharField(
        max_length=50, default='PASARELA_LOCAL', blank=True
    )

    moneda_destino = models.ForeignKey(
        Moneda, on_delete=models.PROTECT, null=True, blank=True,
        related_name='transacciones_destino',
    )
    tasa_cambio_destino = models.DecimalField(
        max_digits=15, decimal_places=6, null=True, blank=True
    )
    cantidad_destino = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    observacion = models.CharField(max_length=255, blank=True, default='')

    COMISION_POR_PREFERENCIA = {
        Cliente.PREFERENCIA_ESTANDAR: Decimal('1.50'),
        Cliente.PREFERENCIA_PREFERENCIAL: Decimal('1.00'),
        Cliente.PREFERENCIA_MAYORISTA: Decimal('0.50'),
    }

    def iniciar_pago_externo(self, referencia, proveedor='PASARELA_LOCAL'):
        """Ticket E4-157: Registra la referencia e inicia la confirmación externa."""
        self.referencia_pago_externo = referencia
        self.proveedor_pago = proveedor
        self.estado = 'PENDIENTE_PAGO'
        self.save()

    def confirmar_pago_webhook(self):
        """Ticket E4-158: Confirma el pago recibido desde el Webhook pasándolo a PAGADO."""
        if self.estado == 'CANCELADA':
            raise ValidationError('No se puede confirmar una transacción cancelada.')
        self.estado = 'PAGADO'
        self.save()

    def calcular_tasas_y_comisiones(self):
        if self.cliente_id:
            self.comision_porcentaje = self.COMISION_POR_PREFERENCIA.get(
                self.cliente.preferencia_tipo_cambio, self.comision_porcentaje
            )

        subtotal = _a_guaranies(self.cantidad * self.tasa_cambio)
        self.monto_comision = _a_guaranies(
            (subtotal * self.comision_porcentaje) / Decimal('100.00')
        )

        if self.tipo == 'COMPRA':
            self.monto_total = subtotal + self.monto_comision
        else:
            self.monto_total = subtotal - self.monto_comision

        desglose = {
            'subtotal': subtotal,
            'comision': self.monto_comision,
            'monto_total': self.monto_total,
        }
        if self.tipo == 'CAMBIO':
            self.cantidad_destino = (self.monto_total / self.tasa_cambio_destino).quantize(
                Decimal('0.01'), rounding=ROUND_DOWN
            )
            desglose['cantidad_destino'] = self.cantidad_destino
        return desglose

    def calcular_monto_total(self):
        res = self.calcular_tasas_y_comisiones()
        return res['monto_total']

    def validar_limite_cliente(self):
        if not self.cliente_id:
            return None

        limite = self.cliente.limite_por_operacion
        if limite is not None and self.monto_total > limite:
            return (
                f'El monto de la operación ({banco.formatear_guaranies(self.monto_total)}) '
                f'supera el límite por operación de la categoría '
                f'{self.cliente.get_categoria_display()} ({banco.formatear_guaranies(limite)}).'
            )
        return None

    def validar(self):
        return self.cantidad > 0 and self.tasa_cambio > 0 and self.metodo_pago.estado

    @property
    def subtotal(self):
        return _a_guaranies(self.cantidad * self.tasa_cambio)

    def confirmar(self):
        with transaction.atomic():
            error = self._procesar_pago()
        if error:
            raise ValidationError(error)

    def _procesar_pago(self):
        self.estado = (
            Transaccion.objects.select_for_update()
            .filter(pk=self.pk).values_list('estado', flat=True).get()
        )
        if self.estado not in ['PENDIENTE', 'PAGADO']:
            return (
                f'Solo se puede confirmar una transacción pendiente '
                f'(esta está {self.get_estado_display().lower()}).'
            )
        if not self.validar():
            return 'La transacción no es válida.'

        cambios, error = self._cambios_de_cotizacion()
        if error:
            return error
        if cambios:
            self.estado = 'CANCELADA'
            self.observacion = 'Cambió la cotización antes del pago.'
            self.save()
            return (
                f'La transacción ha sido cancelada porque la tasa de cambio ha sufrido '
                f'modificaciones ({"; ".join(cambios)}).'
            )

        self.calcular_monto_total()
        error_pago = self._mover_fondos()
        if error_pago:
            self.estado = 'FALLIDA'
            self.observacion = error_pago[:255]
            self.save()
            return f'Pago rechazado. {error_pago} La operación quedó registrada como fallida.'

        self.estado = 'EXITOSA'
        self.save()
        return None

    def _cambios_de_cotizacion(self):
        if self.tipo == 'CAMBIO':
            a_comparar = [
                (self.moneda, 'VENTA', self.tasa_cambio),
                (self.moneda_destino, 'COMPRA', self.tasa_cambio_destino),
            ]
        else:
            a_comparar = [(self.moneda, self.tipo, self.tasa_cambio)]

        cambios = []
        for moneda, operacion, tasa_guardada in a_comparar:
            tasa_obj = moneda.tasas.filter(estado=True).order_by('-fecha_hora').first()
            if not tasa_obj:
                return [], f'No hay una tasa de cambio vigente para {moneda.codigo}.'
            tasa_actual = tasa_obj.tasa_para(operacion)
            if tasa_guardada != tasa_actual:
                detalle = f'se inició a {tasa_guardada:.2f} y la vigente es {tasa_actual:.2f}'
                cambios.append(f'{moneda.codigo}: {detalle}' if self.tipo == 'CAMBIO' else detalle)
        return cambios, None

    def _mover_fondos(self):
        medio = self.medio_pago
        if medio is None or not medio.metodo_pago.usa_banco:
            return None
        if self.tipo == 'CAMBIO':
            return 'El cambio entre divisas solo se puede pagar en efectivo.'
        if self.tipo == 'VENTA' and not medio.metodo_pago.permite_venta:
            return 'Las tarjetas de crédito no se pueden usar para vender divisas.'

        referencia = f'GE-OP-{self.pk}'
        try:
            if self.tipo == 'COMPRA':
                banco.debitar(
                    medio.identificador, self.monto_total,
                    f'Compra de {self.cantidad} {self.moneda.codigo} (GlobalExchange)', referencia,
                )
            else:
                banco.acreditar(
                    medio.identificador, self.monto_total,
                    f'Venta de {self.cantidad} {self.moneda.codigo} (GlobalExchange)', referencia,
                )
        except banco.ErrorBancario as exc:
            return f'{medio.alias}: {exc}'
        return None

    def cancelar(self):
        if self.estado not in ['PENDIENTE', 'PENDIENTE_PAGO']:
            raise ValidationError(
                f'Solo se puede cancelar una transacción pendiente '
                f'(esta está {self.get_estado_display().lower()}).'
            )
        self.estado = 'CANCELADA'
        self.save()

    def cambiar_estado(self, estado):
        if estado not in dict(self.ESTADOS):
            raise ValidationError('Estado de transacción inválido.')
        self.estado = estado
        self.save()

    def __str__(self):
        return f'{self.tipo} #{self.id} - {self.monto_total}'