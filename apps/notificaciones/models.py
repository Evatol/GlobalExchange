from django.db import models
from apps.usuarios.models import Usuario


class Notificaciones(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='notificaciones')
    titulo = models.CharField(max_length=150)
    mensaje = models.TextField()
    tipo = models.CharField(max_length=50)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    leida = models.BooleanField(default=False)

    def marcar_leida(self):
        self.leida = True
        self.save()

    def __str__(self):
        return self.titulo