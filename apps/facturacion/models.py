from django.db import models, transaction
from django.db.models import Q

from apps.transacciones.models import Transaccion


class SecuenciaFactura(models.Model):
    """Último número de cada tipo de documento (factura o nota de crédito) usado en cada
    establecimiento y punto de expedición.

    La numeración legal es correlativa y sin saltos: el contador se bloquea mientras se
    asigna el número, y vive dentro de la misma transacción de base de datos que crea la
    factura, así que si esa transacción se revierte el número no se gasta.
    """

    FACTURA = 'FACTURA'
    NOTA_CREDITO = 'NOTA_CREDITO'

    id = models.AutoField(primary_key=True)
    documento = models.CharField(max_length=15, default=FACTURA)
    establecimiento = models.CharField(max_length=3)
    punto_expedicion = models.CharField(max_length=3)
    ultimo_numero = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['documento', 'establecimiento', 'punto_expedicion'],
                name='secuencia_documento_unica',
            )
        ]

    @classmethod
    def siguiente(cls, establecimiento, punto_expedicion, documento=FACTURA):
        """El próximo número libre de ese tipo de documento para ese establecimiento y
        punto de expedición."""
        with transaction.atomic():
            cls.objects.get_or_create(
                documento=documento, establecimiento=establecimiento,
                punto_expedicion=punto_expedicion,
            )
            secuencia = cls.objects.select_for_update().get(
                documento=documento, establecimiento=establecimiento,
                punto_expedicion=punto_expedicion,
            )
            secuencia.ultimo_numero += 1
            secuencia.save(update_fields=['ultimo_numero'])
            return secuencia.ultimo_numero

    def __str__(self):
        return f'{self.documento} {self.establecimiento}-{self.punto_expedicion}: {self.ultimo_numero}'


class Factura(models.Model):
    """Factura electrónica de una transacción exitosa (RF33).

    Ciclo de vida de las que emite el sistema: nace ``PENDIENTE`` en el mismo instante en
    que la transacción pasa a ``EXITOSA`` (``apps.facturacion.emision``) y se envía al
    proveedor (el simulador o Factura Segura / SIFEN):

    * si el envío falla, sigue ``PENDIENTE`` con el motivo en ``ultimo_error`` y la hora
      del próximo reintento en ``proximo_intento`` (la transacción no se toca);
    * si el proveedor la recibe, queda ``ENVIADA`` con su ``cdc`` hasta que SIFEN la
      apruebe (``EMITIDA``) o la rechace (``RECHAZADA``).

    Una factura ``EMITIDA`` se anula (``ANULADA``) cuando se anula la operación en efectivo
    (E4-196): se emite una ``NotaCredito`` por el total, vinculada a ella (E4-191). Una que
    todavía no se emitió (pendiente o rechazada) se anula sin nota de crédito, porque nunca
    existió para SIFEN.

    En cuanto queda ``EMITIDA`` se le manda al correo del cliente con el PDF adjunto
    (``correo_enviado_en``; si el correo falla, ``correo_error`` y se reintenta).

    Solo una factura ``EMITIDA`` se puede ver en detalle y descargar el cliente
    (``apps.facturacion.services``). ``payload`` guarda los datos tal como se enviaron
    (emisor, receptor, ítem y pago), para que la factura no cambie aunque después
    cambien los datos del cliente o del emisor.

    Una factura creada directamente (los datos de demostración, las pruebas) nace
    ``EMITIDA`` y sin ``correlativo``: su número sale de su id.
    """

    PENDIENTE = 'PENDIENTE'
    ENVIADA = 'ENVIADA'
    EMITIDA = 'EMITIDA'
    RECHAZADA = 'RECHAZADA'
    ANULADA = 'ANULADA'
    ESTADOS = [
        (PENDIENTE, 'Pendiente de envío'),
        (ENVIADA, 'Enviada a SIFEN'),
        (EMITIDA, 'Emitida'),
        (RECHAZADA, 'Rechazada'),
        (ANULADA, 'Anulada'),
    ]
    ESTADO_EMITIDA = EMITIDA

    # Establecimiento y punto de expedición por defecto del número de factura.
    ESTABLECIMIENTO = '001'
    PUNTO_EXPEDICION = '001'

    id = models.AutoField(primary_key=True)
    transaccion = models.OneToOneField(Transaccion, on_delete=models.CASCADE, related_name='factura')
    establecimiento = models.CharField(max_length=3, default=ESTABLECIMIENTO)
    punto_expedicion = models.CharField(max_length=3, default=PUNTO_EXPEDICION)
    correlativo = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Número correlativo de la factura (sale de SecuenciaFactura).',
    )
    timbrado = models.CharField(max_length=8, blank=True, default='')
    cdc = models.CharField(
        'CDC', max_length=44, blank=True, default='',
        help_text='Código de control que SIFEN asigna al documento (44 dígitos).',
    )
    monto = models.DecimalField(max_digits=15, decimal_places=2)
    fecha = models.DateField(auto_now_add=True)
    fecha_emision = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=30, choices=ESTADOS, default=EMITIDA)
    proveedor = models.CharField(max_length=30, blank=True, default='')
    estado_sifen = models.CharField(max_length=255, blank=True, default='')
    intentos = models.PositiveSmallIntegerField(default=0)
    ultimo_error = models.CharField(max_length=255, blank=True, default='')
    proximo_intento = models.DateTimeField(null=True, blank=True)
    correo_enviado_en = models.DateTimeField(
        null=True, blank=True,
        help_text='Cuándo se le mandó la factura al correo del cliente (solo si está emitida).',
    )
    correo_error = models.CharField(max_length=255, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    respuesta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-id']
        constraints = [
            models.UniqueConstraint(
                fields=['establecimiento', 'punto_expedicion', 'correlativo'],
                name='factura_numero_unico',
            ),
            models.UniqueConstraint(
                fields=['cdc'], condition=~Q(cdc=''), name='factura_cdc_unico'
            ),
        ]

    def generar(self):
        """Completa y guarda una factura creada a mano (los datos de demostración): el
        monto de la operación y, si no tiene, su número correlativo, para que no se
        repita con las que emite el sistema."""
        self.monto = self.transaccion.monto_total
        if self.correlativo is None:
            self.correlativo = SecuenciaFactura.siguiente(
                self.establecimiento, self.punto_expedicion
            )
        self.save()
        EventoFactura.registrar(self, EventoFactura.EMISION, detalle='Factura de demostración')

    def emitir(self):
        self.estado = self.ESTADO_EMITIDA
        self.save()

    @property
    def esta_emitida(self):
        """True si la factura está en estado emitida."""
        return self.estado == self.ESTADO_EMITIDA

    @property
    def es_consultable(self):
        """True si el cliente puede ver y descargar la factura: la emitida y la que
        después se anuló (que sigue existiendo, con su nota de crédito)."""
        return self.estado in (self.EMITIDA, self.ANULADA)

    @property
    def numero(self):
        """Número de factura con formato fiscal, por ejemplo ``001-001-0000042``: el
        correlativo, o el id si la factura no tiene (las de demostración)."""
        return f'{self.establecimiento}-{self.punto_expedicion}-{self.correlativo or self.pk or 0:07d}'

    def __str__(self):
        return f'Factura {self.numero}'


class NotaCredito(models.Model):
    """Nota de crédito electrónica que anula una factura emitida (E4-191).

    Se crea ``PENDIENTE`` en el mismo instante en que se anula la factura, por el **monto
    total**, con su propia numeración (``SecuenciaFactura``) y referenciando el CDC de la
    factura original (``gCamDEAsoc`` en el documento). Sigue el mismo recorrido que la
    factura: se envía al proveedor, se reintenta si falla y queda ``EMITIDA`` o
    ``RECHAZADA`` cuando SIFEN resuelve (``apps.facturacion.emision``).
    """

    PENDIENTE = 'PENDIENTE'
    ENVIADA = 'ENVIADA'
    EMITIDA = 'EMITIDA'
    RECHAZADA = 'RECHAZADA'
    ESTADOS = [
        (PENDIENTE, 'Pendiente de envío'),
        (ENVIADA, 'Enviada a SIFEN'),
        (EMITIDA, 'Emitida'),
        (RECHAZADA, 'Rechazada'),
    ]

    id = models.AutoField(primary_key=True)
    factura = models.OneToOneField(Factura, on_delete=models.CASCADE, related_name='nota_credito')
    establecimiento = models.CharField(max_length=3, default=Factura.ESTABLECIMIENTO)
    punto_expedicion = models.CharField(max_length=3, default=Factura.PUNTO_EXPEDICION)
    correlativo = models.PositiveIntegerField(null=True, blank=True)
    timbrado = models.CharField(max_length=8, blank=True, default='')
    cdc = models.CharField('CDC', max_length=44, blank=True, default='')
    monto = models.DecimalField(max_digits=15, decimal_places=2)
    motivo = models.CharField(max_length=255, blank=True, default='')
    fecha_emision = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=30, choices=ESTADOS, default=PENDIENTE)
    proveedor = models.CharField(max_length=30, blank=True, default='')
    estado_sifen = models.CharField(max_length=255, blank=True, default='')
    intentos = models.PositiveSmallIntegerField(default=0)
    ultimo_error = models.CharField(max_length=255, blank=True, default='')
    proximo_intento = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    respuesta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-id']
        constraints = [
            models.UniqueConstraint(
                fields=['establecimiento', 'punto_expedicion', 'correlativo'],
                name='nota_credito_numero_unico',
            ),
            models.UniqueConstraint(
                fields=['cdc'], condition=~Q(cdc=''), name='nota_credito_cdc_unico'
            ),
        ]

    @property
    def esta_emitida(self):
        return self.estado == self.EMITIDA

    @property
    def numero(self):
        """Número con formato fiscal, por ejemplo ``001-001-0000003``."""
        return f'{self.establecimiento}-{self.punto_expedicion}-{self.correlativo or self.pk or 0:07d}'

    def __str__(self):
        return f'Nota de crédito {self.numero}'


class _EventosInalterables(models.QuerySet):
    """El registro de auditoría solo se agrega: no se actualiza ni se borra en bloque."""

    def update(self, **kwargs):
        raise PermissionError(EventoFactura.MENSAJE_INALTERABLE)

    def delete(self):
        raise PermissionError(EventoFactura.MENSAJE_INALTERABLE)

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionError(EventoFactura.MENSAJE_INALTERABLE)


class EventoFactura(models.Model):
    """Registro de auditoría de una factura (E4-191, RF98): quién hizo qué y cuándo.

    Se registra la **emisión**, la **descarga** y la **anulación** de la factura (y la
    emisión de su nota de crédito). Es un registro inalterable: una vez creado no se
    puede modificar ni borrar (ni por instancia ni en bloque), y no se borra junto con la
    factura (``PROTECT``), para asegurar la trazabilidad fiscal.
    """

    EMISION = 'EMISION'
    DESCARGA = 'DESCARGA'
    ANULACION = 'ANULACION'
    NOTA_CREDITO = 'NOTA_CREDITO'
    TIPOS = [
        (EMISION, 'Emisión'),
        (DESCARGA, 'Descarga'),
        (ANULACION, 'Anulación'),
        (NOTA_CREDITO, 'Nota de crédito emitida'),
    ]
    USUARIO_SISTEMA = 'sistema'
    MENSAJE_INALTERABLE = 'Los eventos de auditoría de las facturas no se pueden modificar ni borrar.'

    id = models.AutoField(primary_key=True)
    factura = models.ForeignKey(Factura, on_delete=models.PROTECT, related_name='eventos')
    tipo = models.CharField(max_length=20, choices=TIPOS)
    usuario = models.CharField(max_length=150, default=USUARIO_SISTEMA)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    detalle = models.CharField(max_length=255, blank=True, default='')

    objects = _EventosInalterables.as_manager()

    class Meta:
        ordering = ['id']

    @classmethod
    def registrar(cls, factura, tipo, usuario=None, detalle=''):
        """Agrega un evento. ``usuario`` es un usuario, su nombre o ``None`` (el sistema)."""
        nombre = getattr(usuario, 'username', usuario) or cls.USUARIO_SISTEMA
        return cls.objects.create(
            factura=factura, tipo=tipo, usuario=str(nombre), detalle=detalle[:255]
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError(self.MENSAJE_INALTERABLE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(self.MENSAJE_INALTERABLE)

    def __str__(self):
        return f'{self.get_tipo_display()} de {self.factura.numero} por {self.usuario}'
