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


class TasaCambioQuerySet(models.QuerySet):
    def activa_para(self, moneda_codigo):
        """Última cotización activa de una moneda (por código), o ``None``.

        Consulta única compartida por la vista pública en HTML
        (``PantallaPublicaCambiosView``) y el simulador por API
        (``SimuladorConversionView``), para no repetir el mismo filtro en
        dos lugares.
        """
        return (
            self.filter(moneda__codigo__iexact=moneda_codigo, estado=True)
            .order_by('-fecha_hora')
            .first()
        )

    def vigentes(self):
        """La cotización vigente de cada moneda activa: la última activa,
        que es la que ``activa_para`` le aplica a una operación. Para mostrar
        "el cambio del día" sin repetir monedas que tengan cotizaciones
        anteriores todavía activas."""
        ultimas = (
            self.filter(estado=True, moneda__estado=True)
            .order_by('moneda_id', '-fecha_hora')
            .distinct('moneda_id')
            .values('id')
        )
        return self.filter(id__in=ultimas).select_related('moneda').order_by('moneda_id')


class TasaCambio(models.Model):
    id = models.AutoField(primary_key=True)
    moneda = models.ForeignKey(Moneda, on_delete=models.PROTECT, related_name='tasas')
    tasa_compra = models.DecimalField(max_digits=15, decimal_places=6)
    tasa_venta = models.DecimalField(max_digits=15, decimal_places=6)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    origen = models.CharField(max_length=100)
    estado = models.BooleanField(default=True)

    objects = TasaCambioQuerySet.as_manager()

    def _formatear_valor(self, valor):
        """Formatea el valor decimal para ocultar ceros innecesarios en la vista."""
        if valor is None:
            return ""
        if valor % 1 == 0:
            return f"{int(valor):,}".replace(",", ".")
        texto = f"{valor:.6f}".rstrip('0').rstrip('.')
        return texto.replace(".", ",")

    def tasa_para(self, operacion):
        """Tasa que se le aplica al cliente según la operación que hace.

        ``tasa_compra`` y ``tasa_venta`` son las de la pizarra de la casa de
        cambio, desde el punto de vista de la casa: a cuánto *compra* y a
        cuánto *vende* la divisa. Por eso se cruzan con la operación del
        cliente:

        * el cliente **compra** divisas → la casa le vende → ``tasa_venta``;
        * el cliente **vende** divisas → la casa se las compra → ``tasa_compra``.

        Así el cliente siempre compra al precio más alto y vende al más bajo,
        y la diferencia (el *spread*) queda para la casa. Al revés, una compra
        y una venta seguidas le dejaban ganancia al cliente.

        Es el único lugar donde se decide esto: la usan el simulador, la
        operación de compra/venta y la confirmación del pago (E4-28), que
        tienen que coincidir siempre.

        ``operacion``: ``'COMPRA'`` o ``'VENTA'`` (sin importar mayúsculas).
        """
        operacion = str(operacion).upper()
        if operacion == 'COMPRA':
            return self.tasa_venta
        if operacion == 'VENTA':
            return self.tasa_compra
        raise ValueError(f'Operación inválida: {operacion!r} (debe ser COMPRA o VENTA).')

    def obtener_tasa_compra(self):
        return self.tasa_compra

    def obtener_tasa_venta(self):
        return self.tasa_venta

    def obtener_tasa_compra_formateada(self):
        return self._formatear_valor(self.tasa_compra)

    def obtener_tasa_venta_formateada(self):
        return self._formatear_valor(self.tasa_venta)

    def actualizar_tasa_compra(self, tasa):
        self.tasa_compra = tasa
        self.save()

    def actualizar_tasa_venta(self, tasa):
        self.tasa_venta = tasa
        self.save()

    def __str__(self):
        return f'{self.moneda.codigo} - {self.obtener_tasa_venta_formateada()}'


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