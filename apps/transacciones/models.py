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

    Sin esto, el cálculo intermedio arrastra la precisión de ``tasa_cambio``
    (6 decimales) y los montos se muestran como ``67935.99000000`` en los
    mensajes de la pantalla y en las respuestas de la API, aunque en la base
    queden bien.
    """
    return monto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class MetodoPago(models.Model):
    """Catálogo de métodos de pago admitidos (transferencia, billetera, efectivo…).

    El ``tipo`` define cómo se cobra: el efectivo no pasa por el banco; los
    demás se asocian a una cuenta del banco simulado del tipo equivalente
    (``CUENTA_BANCO_POR_TIPO``), cuyo disponible se descuenta en cada compra
    y se acredita en cada venta. La tarjeta de crédito solo sirve para
    comprar: en una venta el cliente recibe plata, y eso no se acredita en
    una tarjeta.
    """

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

    # Tipo de cuenta del banco que respalda a cada método. El efectivo no
    # está: no tiene saldo.
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
        """True si se paga desde una cuenta del banco (todo menos efectivo)."""
        return self.tipo in self.CUENTA_BANCO_POR_TIPO

    @property
    def tipo_cuenta_banco(self):
        return self.CUENTA_BANCO_POR_TIPO.get(self.tipo)

    @property
    def permite_venta(self):
        """En una venta el cliente recibe la plata: no se acredita en una tarjeta."""
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
    """Medio de pago concreto registrado por un cliente (RF17).

    Un cliente puede tener varios: una cuenta bancaria, una billetera
    electrónica, etc. ``metodo_pago`` es el tipo (del catálogo) e
    ``identificador`` guarda el nº de cuenta / alias de billetera / etc.

    Salvo el efectivo, el ``identificador`` es el número de una cuenta del
    banco simulado, del tipo que corresponde y a nombre del cliente: de ahí
    sale el disponible con el que se paga.
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
        error = self.validar_cuenta_banco()
        if error:
            raise ValidationError({'identificador': error})

    def validar_cuenta_banco(self):
        """``None`` si el medio es efectivo o si su cuenta existe en el banco,
        es del tipo correcto y está a nombre del cliente; si no, el mensaje."""
        if not self.metodo_pago_id or not self.cliente_id or not self.metodo_pago.usa_banco:
            return None
        return banco.verificar_titular(
            self.identificador, self.metodo_pago.tipo_cuenta_banco, self.cliente.documento
        )

    @property
    def cuenta_banco(self):
        """La cuenta del banco que respalda este medio (``None`` si es efectivo)."""
        if not self.metodo_pago.usa_banco:
            return None
        return banco.buscar_cuenta(self.identificador)

    @property
    def disponible(self):
        """Disponible en el banco, o ``None`` si es efectivo (no tiene saldo)."""
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
    """Operación de un cliente: compra o venta de divisas contra guaraníes
    (E4-19/E4-20), o cambio de una divisa por otra (``CAMBIO``).

    Ciclo de vida: se crea ``PENDIENTE`` con la tasa vigente en ese momento
    y su comisión ya calculada (E4-144). Desde ahí, ``confirmar()`` (el
    pago) la pasa a ``EXITOSA``, salvo que la cotización haya cambiado en el
    medio, en cuyo caso la cancela (E4-28), o que el banco rechace el pago
    por falta de saldo, en cuyo caso queda ``FALLIDA``; ``cancelar()`` la
    cancela a pedido del usuario (RF23). ``EXITOSA``, ``CANCELADA`` y
    ``FALLIDA`` son estados finales.

    En un ``CAMBIO``, ``moneda``/``cantidad``/``tasa_cambio`` son los de la
    divisa que entrega el cliente, y ``moneda_destino``/``cantidad_destino``/
    ``tasa_cambio_destino`` los de la que recibe. La conversión pasa por el
    guaraní, como en una casa de cambio real: la casa le compra la divisa de
    origen y le vende la de destino.
    """

    TIPOS = [
        ('COMPRA', 'Compra'),
        ('VENTA', 'Venta'),
        ('CAMBIO', 'Cambio entre divisas'),
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
    # El medio concreto del cliente (qué cuenta o tarjeta), para saber de
    # dónde se cobra. Nulo en las operaciones anteriores a que existiera.
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
    # Solo en un CAMBIO: la divisa que recibe el cliente.
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
    # Por qué terminó así (ej. el rechazo del banco en una FALLIDA).
    observacion = models.CharField(max_length=255, blank=True, default='')

    # Comisión según la preferencia de tipo de cambio del cliente (RF41):
    # Mayorista y Preferencial pagan menos comisión que Estándar.
    COMISION_POR_PREFERENCIA = {
        Cliente.PREFERENCIA_ESTANDAR: Decimal('1.50'),
        Cliente.PREFERENCIA_PREFERENCIAL: Decimal('1.00'),
        Cliente.PREFERENCIA_MAYORISTA: Decimal('0.50'),
    }

    def calcular_tasas_y_comisiones(self):
        """
        Lógica del Ticket E4-144:
        Calcula el subtotal, la comisión aplicada (según la preferencia de
        tipo de cambio del cliente, si hay uno asociado) y el monto total
        definitivo de la transacción.

        En un ``CAMBIO`` el subtotal es lo que vale en guaraníes la divisa
        que entrega el cliente; se le descuenta la comisión y lo que queda
        (``monto_total``) se convierte a la divisa de destino. Se redondea
        hacia abajo: la casa no entrega centavos que no cubrió.
        """
        if self.cliente_id:
            self.comision_porcentaje = self.COMISION_POR_PREFERENCIA.get(
                self.cliente.preferencia_tipo_cambio, self.comision_porcentaje
            )

        subtotal = _a_guaranies(self.cantidad * self.tasa_cambio)
        self.monto_comision = _a_guaranies(
            (subtotal * self.comision_porcentaje) / Decimal('100.00')
        )

        if self.tipo == 'COMPRA':
            # Al comprar divisas, el cliente paga el subtotal + la comisión del servicio
            self.monto_total = subtotal + self.monto_comision
        else:
            # Al vender divisas, el cliente recibe el subtotal - la comisión
            # del servicio. En un cambio, eso es lo que se convierte a destino.
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
        """E4-143 (RF41): el monto de la operación no puede superar el límite
        por operación de la categoría del cliente (Minorista 100.000 Gs,
        Mayorista 1.000.000 Gs, VIP sin límite). Aplica igual a compras,
        ventas y cambios, siempre sobre el ``monto_total`` en guaraníes.

        Devuelve ``None`` si está dentro del límite, o el mensaje de error
        correspondiente si lo supera. Requiere que ``monto_total`` ya esté
        calculado (``calcular_tasas_y_comisiones``).
        """
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
        """Cantidad por tasa aplicada, antes de la comisión (en guaraníes)."""
        return _a_guaranies(self.cantidad * self.tasa_cambio)

    def confirmar(self):
        """Confirma el pago de una transacción ``PENDIENTE`` (E4-28).

        Antes de confirmar vuelve a leer la cotización vigente y la compara
        con la tasa guardada cuando se inició la operación (en un cambio,
        las de las dos divisas):

        * si cambió, la transacción pasa a ``CANCELADA``;
        * si no, se cobra (compra) o se paga (venta) en la cuenta del banco
          del medio de pago. Si el banco la rechaza (por ejemplo, por saldo
          insuficiente) la transacción pasa a ``FALLIDA``;
        * si el banco la acepta, pasa a ``EXITOSA``.

        Cancelada o fallida, lanza ``ValidationError`` con el motivo.

        Solo se puede confirmar una transacción pendiente: sin esa guarda,
        una transacción ya cancelada podía volver a confirmarse si la
        cotización regresaba a su valor original. La fila queda bloqueada
        mientras se procesa, para que dos confirmaciones simultáneas no
        cobren dos veces.
        """
        with transaction.atomic():
            error = self._procesar_pago()
        if error:
            raise ValidationError(error)

    def _procesar_pago(self):
        """Lo que hace ``confirmar()``, dentro de su transacción. Devuelve el
        mensaje de error en vez de lanzarlo, para que el cambio de estado
        (cancelada o fallida) se guarde igual."""
        self.estado = (
            Transaccion.objects.select_for_update()
            .filter(pk=self.pk).values_list('estado', flat=True).get()
        )
        if self.estado != 'PENDIENTE':
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
        """Compara las tasas guardadas con las vigentes. Devuelve
        ``(cambios, error)``: la lista de las que cambiaron (vacía si
        ninguna) o el error si alguna moneda ya no tiene cotización."""
        if self.tipo == 'CAMBIO':
            # La casa le compra la divisa de origen y le vende la de destino.
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
            # Misma regla que al crearla: si no, cancelaría todo (ver tasa_para).
            tasa_actual = tasa_obj.tasa_para(operacion)
            if tasa_guardada != tasa_actual:
                detalle = f'se inició a {tasa_guardada:.2f} y la vigente es {tasa_actual:.2f}'
                cambios.append(f'{moneda.codigo}: {detalle}' if self.tipo == 'CAMBIO' else detalle)
        return cambios, None

    def _mover_fondos(self):
        """Cobra la compra o paga la venta en la cuenta del banco del medio
        de pago. Devuelve el motivo si el banco la rechaza, o ``None``. El
        efectivo no pasa por el banco."""
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
        """Cancela a pedido del usuario una transacción todavía no pagada (RF23).

        Solo aplica a transacciones ``PENDIENTE``: una exitosa ya se pagó y
        una cancelada ya terminó.
        """
        if self.estado != 'PENDIENTE':
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
