from django.contrib import admin
from .models import (
    Proyecto, AsignacionProyecto, Sprint, Backlog,
    Workflow, Actividad, Estado, UserStory, Nota, Worklog
)

admin.site.register(Proyecto)
admin.site.register(AsignacionProyecto)
admin.site.register(Sprint)
admin.site.register(Backlog)
admin.site.register(Workflow)
admin.site.register(Actividad)
admin.site.register(Estado)
admin.site.register(UserStory)
admin.site.register(Nota)
admin.site.register(Worklog)