from django.db import models
from apps.transacciones.models import Transaccion


class Factura(models.Model):
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

    def __str__(self):
        return f'Factura #{self.id}'