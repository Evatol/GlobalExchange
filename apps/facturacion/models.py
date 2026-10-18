from django.db import models
from apps.transacciones.models import Transaccion


class Factura(models.Model):
    ESTADO_EMITIDA = 'EMITIDA'
    # Establecimiento y punto de expedición del número de factura (demo).
    ESTABLECIMIENTO = '001'
    PUNTO_EXPEDICION = '001'

    id = models.AutoField(primary_key=True)
    transaccion = models.OneToOneField(Transaccion, on_delete=models.CASCADE, related_name='factura')
    monto = models.DecimalField(max_digits=15, decimal_places=2)
    fecha = models.DateField(auto_now_add=True)
    estado = models.CharField(max_length=30, default='EMITIDA')

    def generar(self):
        self.monto = self.transaccion.monto_total
        self.save()

    def emitir(self):
        self.estado = 'EMITIDA'
        self.save()

    @property
    def numero(self):
        """Número de factura con formato fiscal, por ejemplo ``001-001-0000042``."""
        return f'{self.ESTABLECIMIENTO}-{self.PUNTO_EXPEDICION}-{self.pk or 0:07d}'

    @property
    def esta_emitida(self):
        """True si la factura está en estado emitida."""
        return self.estado == self.ESTADO_EMITIDA

    def __str__(self):
        return f'Factura #{self.id}'