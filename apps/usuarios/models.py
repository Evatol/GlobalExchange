from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Permiso(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()

    def __str__(self):
        return self.nombre


class Rol(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField()
    permisos = models.ManyToManyField(
        Permiso,
        blank=True,
        related_name='roles'
    )

    def __str__(self):
        return self.nombre


class Cliente(models.Model):
    """Cliente (persona física o jurídica) sobre el que operan los usuarios.

    Cubre RF40 (niveles/categorías entre clientes), RF41 (preferencias:
    frecuencia, límites de compra/venta, preferencia de tipo de cambio) y
    RF42 (un cliente asociado a uno o más usuarios, vía ``Usuario.clientes``).
    """

    TIPO_CHOICES = [
        ('FISICA', 'Persona física'),
        ('JURIDICA', 'Persona jurídica'),
    ]

    # RF40: niveles o categorías (segmentación) de los clientes.
    CATEGORIA_MINORISTA = 'MINORISTA'
    CATEGORIA_CORPORATIVO = 'CORPORATIVO'
    CATEGORIA_VIP = 'VIP'
    CATEGORIA_CHOICES = [
        (CATEGORIA_MINORISTA, 'Minorista'),
        (CATEGORIA_CORPORATIVO, 'Corporativo'),
        (CATEGORIA_VIP, 'VIP'),
    ]

    # RF41: preferencia de tipo de cambio aplicada al cliente.
    PREFERENCIA_ESTANDAR = 'ESTANDAR'
    PREFERENCIA_PREFERENCIAL = 'PREFERENCIAL'
    PREFERENCIA_MAYORISTA = 'MAYORISTA'
    PREFERENCIA_TIPO_CAMBIO_CHOICES = [
        (PREFERENCIA_ESTANDAR, 'Estándar'),
        (PREFERENCIA_PREFERENCIAL, 'Preferencial'),
        (PREFERENCIA_MAYORISTA, 'Mayorista'),
    ]

    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    razon_social = models.CharField(max_length=200, blank=True, default='')
    documento = models.CharField(
        'documento / RUC',
        max_length=50,
        unique=True,
        help_text='Documento de identidad o RUC. Identificador único del cliente.',
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    categoria = models.CharField(
        max_length=20,
        choices=CATEGORIA_CHOICES,
        default=CATEGORIA_MINORISTA,
    )
    estado = models.BooleanField('activo', default=True)
    limite_compra = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    limite_venta = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal('0.00')
    )
    frecuencia_transacciones = models.IntegerField(default=0)
    preferencia_tipo_cambio = models.CharField(
        max_length=20,
        choices=PREFERENCIA_TIPO_CAMBIO_CHOICES,
        default=PREFERENCIA_ESTANDAR,
    )
    fecha_creacion = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']

    def clean(self):
        errores = {}
        if self.limite_compra is not None and self.limite_compra < 0:
            errores['limite_compra'] = 'El límite de compra no puede ser negativo.'
        if self.limite_venta is not None and self.limite_venta < 0:
            errores['limite_venta'] = 'El límite de venta no puede ser negativo.'
        if self.frecuencia_transacciones is not None and self.frecuencia_transacciones < 0:
            errores['frecuencia_transacciones'] = (
                'La frecuencia de transacciones no puede ser negativa.'
            )
        if self.tipo == self.__class__.TIPO_CHOICES[1][0] and not self.razon_social:
            errores['razon_social'] = (
                'La razón social es obligatoria para personas jurídicas.'
            )
        if errores:
            raise ValidationError(errores)

    def actualizar_categoria(self, categoria):
        self.categoria = categoria
        self.save()

    def establecer_limite_compra(self, limite):
        self.limite_compra = limite
        self.save()

    def establecer_limite_venta(self, limite):
        self.limite_venta = limite
        self.save()

    def establecer_frecuencia(self, frecuencia):
        self.frecuencia_transacciones = frecuencia
        self.save()

    def asociar_usuario(self, usuario):
        self.usuarios.add(usuario)

    def desasociar_usuario(self, usuario):
        self.usuarios.remove(usuario)

    def __str__(self):
        return self.nombre


class Usuario(models.Model):
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30)
    direccion = models.CharField(max_length=200)
    estado = models.BooleanField(default=True)

    clientes = models.ManyToManyField(
        Cliente,
        blank=True,
        related_name='usuarios'
    )
    roles = models.ManyToManyField(
        Rol,
        blank=True,
        related_name='usuarios'
    )

    def actualizar_datos(self, nombres, apellidos, telefono, direccion):
        self.nombres = nombres
        self.apellidos = apellidos
        self.telefono = telefono
        self.direccion = direccion
        self.save()

    def actualizar_estado(self, estado):
        self.estado = estado
        self.save()

    def seleccionar_cliente(self, cliente):
        self.clientes.add(cliente)

    def consultar_historial(self):
        return self.transacciones.all()

    def __str__(self):
        return self.username