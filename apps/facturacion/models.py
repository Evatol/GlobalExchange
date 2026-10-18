from django.db import models, transaction
from django.db.models import Q

from apps.transacciones.models import Transaccion


class SecuenciaFactura(models.Model):
    """Último número de factura usado en cada establecimiento y punto de expedición.

    La numeración legal es correlativa y sin saltos: el contador se bloquea mientras se
    asigna el número, y vive dentro de la misma transacción de base de datos que crea la
    factura, así que si esa transacción se revierte el número no se gasta.
    """

    id = models.AutoField(primary_key=True)
    establecimiento = models.CharField(max_length=3)
    punto_expedicion = models.CharField(max_length=3)
    ultimo_numero = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['establecimiento', 'punto_expedicion'], name='secuencia_factura_unica'
            )
        ]

    @classmethod
    def siguiente(cls, establecimiento, punto_expedicion):
        """El próximo número libre para ese establecimiento y punto de expedición."""
        with transaction.atomic():
            cls.objects.get_or_create(
                establecimiento=establecimiento, punto_expedicion=punto_expedicion
            )
            secuencia = cls.objects.select_for_update().get(
                establecimiento=establecimiento, punto_expedicion=punto_expedicion
            )
            secuencia.ultimo_numero += 1
            secuencia.save(update_fields=['ultimo_numero'])
            return secuencia.ultimo_numero

    def __str__(self):
        return f'{self.establecimiento}-{self.punto_expedicion}: {self.ultimo_numero}'


class Factura(models.Model):
    """Factura electrónica de una transacción exitosa (RF33).

    Ciclo de vida: nace ``PENDIENTE`` en el mismo instante en que la transacción pasa a
    ``EXITOSA`` y se envía al proveedor (el simulador o Factura Segura / SIFEN):

    * si el envío falla, sigue ``PENDIENTE`` con el motivo en ``ultimo_error`` y la hora
      del próximo reintento en ``proximo_intento`` (la transacción no se toca);
    * si el proveedor la recibe, queda ``ENVIADA`` con su ``cdc`` hasta que SIFEN la
      apruebe (``EMITIDA``) o la rechace (``RECHAZADA``).

    En cuanto queda ``EMITIDA`` se le manda al correo del cliente con el PDF adjunto
    (``correo_enviado_en``; si el correo falla, ``correo_error`` y se reintenta).

    Solo una factura ``EMITIDA`` se puede ver en detalle y descargar el cliente.
    ``payload`` guarda los datos tal como se enviaron (emisor, receptor, ítem y pago),
    para que la factura no cambie aunque después cambien los datos del cliente o del
    emisor.
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
    transaccion = models.OneToOneField(Transaccion, on_delete=models.CASCADE, related_name='factura')
    establecimiento = models.CharField(max_length=3, default='001')
    punto_expedicion = models.CharField(max_length=3, default='001')
    numero = models.PositiveIntegerField(null=True, blank=True)
    timbrado = models.CharField(max_length=8, blank=True, default='')
    cdc = models.CharField(
        'CDC', max_length=44, blank=True, default='',
        help_text='Código de control que SIFEN asigna al documento (44 dígitos).',
    )
    monto = models.DecimalField(max_digits=15, decimal_places=2)
    fecha = models.DateField(auto_now_add=True)
    fecha_emision = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=30, choices=ESTADOS, default=PENDIENTE)
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
                fields=['establecimiento', 'punto_expedicion', 'numero'],
                name='factura_numero_unico',
            ),
            models.UniqueConstraint(
                fields=['cdc'], condition=~Q(cdc=''), name='factura_cdc_unico'
            ),
        ]

    @property
    def numero_legal(self):
        """``001-001-0000012``: establecimiento, punto de expedición y número."""
        if self.numero is None:
            return f'#{self.id}'
        return f'{self.establecimiento}-{self.punto_expedicion}-{self.numero:07d}'

    @property
    def esta_emitida(self):
        return self.estado == self.EMITIDA

    def __str__(self):
        return f'Factura {self.numero_legal}'
