from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from apps.divisas.models import Moneda


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
    frecuencia, límites de operación, preferencia de tipo de cambio) y
    RF42 (un cliente asociado a uno o más usuarios, vía ``Usuario.clientes``).

    El límite de cada operación lo fija la categoría (``LIMITE_POR_CATEGORIA``)
    y la comisión, la preferencia de tipo de cambio.
    """

    TIPO_CHOICES = [
        ('FISICA', 'Persona física'),
        ('JURIDICA', 'Persona jurídica'),
    ]

    # RF40: niveles o categorías (segmentación) de los clientes.
    CATEGORIA_MINORISTA = 'MINORISTA'
    CATEGORIA_MAYORISTA = 'MAYORISTA'
    CATEGORIA_VIP = 'VIP'
    CATEGORIA_CHOICES = [
        (CATEGORIA_MINORISTA, 'Minorista'),
        (CATEGORIA_MAYORISTA, 'Mayorista'),
        (CATEGORIA_VIP, 'VIP'),
    ]

    # Monto máximo (en guaraníes) de cada operación según la categoría.
    # ``None`` = sin límite.
    LIMITE_POR_CATEGORIA = {
        CATEGORIA_MINORISTA: Decimal('100000.00'),
        CATEGORIA_MAYORISTA: Decimal('1000000.00'),
        CATEGORIA_VIP: None,
    }

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

    @property
    def limite_por_operacion(self):
        """Monto máximo en guaraníes de cada operación, o ``None`` si no
        tiene límite (VIP)."""
        return self.LIMITE_POR_CATEGORIA.get(self.categoria)

    def actualizar_categoria(self, categoria):
        self.categoria = categoria
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
    monedas_favoritas = models.ManyToManyField(
        Moneda,
        blank=True,
        related_name='usuarios_favoritos',
        limit_choices_to={'estado': True}
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