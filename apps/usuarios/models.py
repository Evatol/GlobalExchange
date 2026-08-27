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
    TIPO_CHOICES = [
        ('FISICA', 'Persona física'),
        ('JURIDICA', 'Persona jurídica'),
    ]

    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    categoria = models.CharField(max_length=100)
    estado = models.BooleanField(default=True)
    limite_compra = models.DecimalField(max_digits=15, decimal_places=2)
    limite_venta = models.DecimalField(max_digits=15, decimal_places=2)
    frecuencia_transacciones = models.IntegerField(default=0)
    preferencia_tipo_cambio = models.CharField(max_length=100)

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