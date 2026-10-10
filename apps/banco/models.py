"""Banco simulado.

Hace de "banco externo" de los medios de pago digitales de los clientes:
cada cuenta bancaria, billetera electrónica o tarjeta de crédito tiene un
disponible en guaraníes que baja con cada compra confirmada y sube con cada
venta. El resto del sistema no modifica estos modelos directamente: pasa
siempre por ``apps.banco.services``.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class CuentaBancaria(models.Model):
    """Cuenta del banco simulado, siempre en guaraníes.

    ``saldo`` es lo que el titular tiene disponible para pagar: el dinero de
    la cuenta o la billetera, o el crédito que le queda a la tarjeta. En una
    tarjeta, ``linea_credito`` es el tope de la línea y lo ya usado es
    ``linea_credito - saldo``.

    El titular se identifica por su documento/RUC, el mismo que el
    ``Cliente`` del sistema: así se verifica que un cliente solo pueda
    asociar como medio de pago cuentas que son suyas.
    """

    TIPO_CUENTA = 'CUENTA'
    TIPO_BILLETERA = 'BILLETERA'
    TIPO_TARJETA_CREDITO = 'TARJETA_CREDITO'
    TIPO_CHOICES = [
        (TIPO_CUENTA, 'Cuenta bancaria'),
        (TIPO_BILLETERA, 'Billetera electrónica'),
        (TIPO_TARJETA_CREDITO, 'Tarjeta de crédito'),
    ]

    id = models.AutoField(primary_key=True)
    numero = models.CharField(
        max_length=100,
        unique=True,
        help_text='Nº de cuenta, de tarjeta o de billetera.',
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    entidad = models.CharField(
        max_length=100,
        help_text='Banco o emisor (ej. "Banco Itaú", "Tigo Money").',
    )
    titular_documento = models.CharField('documento / RUC del titular', max_length=50)
    titular_nombre = models.CharField(max_length=150)
    saldo = models.DecimalField(
        'disponible', max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    linea_credito = models.DecimalField(
        'línea de crédito', max_digits=15, decimal_places=2, default=Decimal('0.00'),
        help_text='Solo para tarjetas de crédito.',
    )
    estado = models.BooleanField('activa', default=True)
    fecha_creacion = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['titular_nombre', 'numero']
        verbose_name = 'cuenta bancaria'
        verbose_name_plural = 'cuentas bancarias'

    @property
    def es_tarjeta(self):
        return self.tipo == self.TIPO_TARJETA_CREDITO

    @property
    def credito_usado(self):
        """Parte de la línea de crédito ya consumida (0 si no es tarjeta)."""
        if not self.es_tarjeta:
            return Decimal('0.00')
        return self.linea_credito - self.saldo

    def clean(self):
        errores = {}
        if self.saldo is not None and self.saldo < 0:
            errores['saldo'] = 'El disponible no puede ser negativo.'
        if self.es_tarjeta:
            if not self.linea_credito or self.linea_credito <= 0:
                errores['linea_credito'] = (
                    'Una tarjeta de crédito necesita una línea de crédito mayor a 0.'
                )
            elif self.saldo is not None and self.saldo > self.linea_credito:
                errores['saldo'] = (
                    'El disponible de la tarjeta no puede superar su línea de crédito.'
                )
        elif self.linea_credito:
            errores['linea_credito'] = 'Solo las tarjetas de crédito tienen línea de crédito.'
        if errores:
            raise ValidationError(errores)

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return f'{self.get_tipo_display()} {self.numero} ({self.titular_nombre})'


class MovimientoBancario(models.Model):
    """Débito o crédito sobre una cuenta, con el saldo que quedó después.

    ``referencia`` identifica la operación del sistema que lo originó (por
    ejemplo ``GE-OP-15``). Es texto y no una FK a ``Transaccion`` a
    propósito: el banco es "externo" y no conoce los modelos de la casa de
    cambio.
    """

    DEBITO = 'DEBITO'
    CREDITO = 'CREDITO'
    TIPO_CHOICES = [
        (DEBITO, 'Débito'),
        (CREDITO, 'Crédito'),
    ]

    id = models.AutoField(primary_key=True)
    cuenta = models.ForeignKey(
        CuentaBancaria, on_delete=models.PROTECT, related_name='movimientos'
    )
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    monto = models.DecimalField(max_digits=15, decimal_places=2)
    saldo_resultante = models.DecimalField(max_digits=15, decimal_places=2)
    concepto = models.CharField(max_length=200)
    referencia = models.CharField(max_length=50, blank=True, default='')
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha_hora', '-id']
        verbose_name = 'movimiento bancario'
        verbose_name_plural = 'movimientos bancarios'

    def __str__(self):
        return f'{self.get_tipo_display()} {self.monto} - {self.cuenta.numero}'
