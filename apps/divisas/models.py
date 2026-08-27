from django.db import models


class Moneda(models.Model):
    id = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=100)
    simbolo = models.CharField(max_length=10)
    estado = models.BooleanField(default=True)

    def activar(self):
        self.estado = True
        self.save()

    def desactivar(self):
        self.estado = False
        self.save()

    def __str__(self):
        return self.codigo


class TasaCambio(models.Model):
    id = models.AutoField(primary_key=True)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='tasas')
    tasa_compra = models.DecimalField(max_digits=15, decimal_places=6)
    tasa_venta = models.DecimalField(max_digits=15, decimal_places=6)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    origen = models.CharField(max_length=100)
    estado = models.BooleanField(default=True)

    def obtener_tasa_compra(self):
        return self.tasa_compra

    def obtener_tasa_venta(self):
        return self.tasa_venta

    def actualizar_tasa_compra(self, tasa):
        self.tasa_compra = tasa
        self.save()

    def actualizar_tasa_venta(self, tasa):
        self.tasa_venta = tasa
        self.save()

    def __str__(self):
        return f'{self.moneda.codigo} - {self.tasa_venta}'


class Simulacion(models.Model):
    id = models.AutoField(primary_key=True)
    tipo_operacion = models.CharField(max_length=30)
    cantidad = models.DecimalField(max_digits=15, decimal_places=2)
    resultado = models.DecimalField(max_digits=15, decimal_places=2)
    fecha_hora = models.DateTimeField(auto_now_add=True)

    def calcular_conversion(self, cantidad, tasa):
        return cantidad * tasa

    def simular_compra(self, cantidad, tasa):
        return self.calcular_conversion(cantidad, tasa)

    def simular_venta(self, cantidad, tasa):
        return self.calcular_conversion(cantidad, tasa)