from django.db import models
from django.core.exceptions import ValidationError
from apps.usuarios.models import Usuario, Rol


class Proyecto(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('ACTIVO', 'Activo'),
        ('FINALIZADO', 'Finalizado'),
        ('SUSPENDIDO', 'Suspendido'),
        ('CANCELADO', 'Cancelado'),
    ]

    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')

    def cambiar_estado(self, estado):
        estados_validos = dict(self.ESTADOS)
        if estado not in estados_validos:
            raise ValidationError('Estado de proyecto inválido.')
        self.estado = estado
        self.save()

    def activar(self):
        self.cambiar_estado('ACTIVO')

    def finalizar(self):
        self.cambiar_estado('FINALIZADO')

    def suspender(self):
        self.cambiar_estado('SUSPENDIDO')

    def cancelar(self):
        self.cambiar_estado('CANCELADO')

    def __str__(self):
        return self.nombre


class AsignacionProyecto(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='asignaciones')
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='asignaciones')
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name='asignaciones')
    fecha_asignacion = models.DateField(auto_now_add=True)

    def cambiar_rol(self, nuevo_rol):
        self.rol = nuevo_rol
        self.save()

    def __str__(self):
        return f'{self.usuario.username} - {self.proyecto.nombre}'


class Sprint(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('ACTIVO', 'Activo'),
        ('FINALIZADO', 'Finalizado'),
        ('SUSPENDIDO', 'Suspendido'),
        ('CANCELADO', 'Cancelado'),
    ]

    id = models.AutoField(primary_key=True)
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='sprints')
    nombre = models.CharField(max_length=150)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    duracion = models.IntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')

    def calcular_duracion(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValidationError('La fecha final no puede ser anterior a la fecha inicial.')
        self.duracion = (self.fecha_fin - self.fecha_inicio).days
        return self.duracion

    def save(self, *args, **kwargs):
        self.calcular_duracion()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Backlog(models.Model):
    id = models.AutoField(primary_key=True)
    proyecto = models.OneToOneField(Proyecto, on_delete=models.CASCADE, related_name='backlog')
    descripcion = models.TextField()

    def agregar_user_story(self, user_story):
        user_story.backlog = self
        user_story.save()

    def listar_user_stories(self):
        return self.user_stories.all()

    def __str__(self):
        return f'Backlog - {self.proyecto.nombre}'


class Workflow(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)

    def agregar_actividad(self, actividad):
        actividad.workflow = self
        actividad.save()

    def listar_actividades(self):
        return self.actividades.all()

    def visualizar_kanban(self):
        return self.user_stories.all()

    def __str__(self):
        return self.nombre


class Actividad(models.Model):
    id = models.AutoField(primary_key=True)
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='actividades')
    nombre = models.CharField(max_length=150)
    orden = models.IntegerField()

    def agregar_estado(self, estado):
        estado.actividad = self
        estado.save()

    def listar_estados(self):
        return self.estados.all()

    def __str__(self):
        return self.nombre


class Estado(models.Model):
    id = models.AutoField(primary_key=True)
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, related_name='estados')
    nombre = models.CharField(max_length=50)
    orden = models.IntegerField()

    def es_finalizado(self):
        return self.nombre == 'Done'

    def __str__(self):
        return self.nombre


class UserStory(models.Model):
    id = models.AutoField(primary_key=True)
    backlog = models.ForeignKey(Backlog, on_delete=models.CASCADE, related_name='user_stories')
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_stories')
    workflow = models.ForeignKey(Workflow, on_delete=models.PROTECT, related_name='user_stories')
    estado = models.ForeignKey(Estado, on_delete=models.PROTECT, null=True, blank=True, related_name='user_stories')
    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='user_stories')
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    prioridad = models.IntegerField(default=0)
    urgencia = models.IntegerField(default=0)
    horas_estimadas = models.IntegerField(default=0)
    valor_tecnico = models.IntegerField(default=0)
    valor_negocio = models.IntegerField(default=0)
    estado_finalizacion = models.CharField(max_length=30, default='To-Do')
    aprobado = models.BooleanField(default=False)
    horas_trabajadas = models.IntegerField(default=0)

    def calcular_prioridad(self):
        self.prioridad = self.urgencia
        return self.prioridad

    def modificar_urgencia(self, urgencia):
        self.urgencia = urgencia
        self.calcular_prioridad()
        self.save()

    def modificar_horas_estimadas(self, horas):
        self.horas_estimadas = horas
        self.save()

    def asignar_usuario(self, usuario):
        self.usuario = usuario
        self.save()

    def desasignar_usuario(self):
        self.usuario = None
        self.save()

    def asignar_estado(self, estado):
        self.estado = estado
        self.save()

    def registrar_horas(self, horas):
        if horas <= 0:
            raise ValidationError('Las horas deben ser mayores a cero.')
        self.horas_trabajadas += horas
        self.save()

    def calcular_horas_trabajadas(self):
        return self.horas_trabajadas

    def calcular_horas_restantes(self):
        return max(self.horas_estimadas - self.horas_trabajadas, 0)

    def aprobar(self):
        self.aprobado = True
        self.save()

    def marcar_finalizado(self):
        self.estado_finalizacion = 'Done'
        self.save()

    def __str__(self):
        return self.titulo


class Nota(models.Model):
    id = models.AutoField(primary_key=True)
    user_story = models.ForeignKey(UserStory, on_delete=models.CASCADE, related_name='notas')
    contenido = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def modificar_contenido(self, contenido):
        self.contenido = contenido
        self.save()

    def __str__(self):
        return f'Nota {self.id}'


class Worklog(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='worklogs')
    user_story = models.ForeignKey(UserStory, on_delete=models.CASCADE, related_name='worklogs')
    horas = models.IntegerField()
    fecha = models.DateField()
    descripcion = models.TextField()

    def registrar_horas(self):
        self.user_story.registrar_horas(self.horas)

    def __str__(self):
        return f'Worklog {self.id}'