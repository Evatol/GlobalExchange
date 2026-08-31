# Registro de Conversaciones con IA (CHIA) - Sprint 1

* Integrante: #4 Eduardo Irala
* Rol / Epic: Epic 4 - Gestión y Calidad (Scrum Master)
* Fecha: Agosto 2026

## 1. Resumen de Interacciones
Durante el desarrollo del Sprint 1, mantuve consultas con la Inteligencia Artificial enfocadas en cumplir mis responsabilidades como Scrum Master y desarrollar los requerimientos de la app `proyectos` en Django[cite: 1, 3]:
* Creación y Documentación CHIA (Ticket E4-128): Asistencia en la estructuración de carpetas en PyCharm, solución del error de identidad de usuario en Git (`Author identity unknown`) mediante `git config`, y publicación de la rama `feature/E4-128-chia-docs` con Pull Request hacia `develop`[cite: 2, 3].
* Planificación del Sprint 2 (Ticket E4-129): Definición del alcance del Hito 4 (CRUD de Monedas, Cotizaciones, Medios de Pago y Simulador)[cite: 2], estructuración de tareas en el Backlog de Jira e inicio del Sprint[cite: 3].
* Desarrollo Backend en Django (Tickets E4-65, E4-68 y E4-69): Implementación de los modelos `Sprint` y `UserStory` en `apps/proyectos/models.py`[cite: 3], configuración personalizada del panel de administración mediante `@admin.register` en `admin.py`, ejecución de migraciones en PostgreSQL y cierre vía Git Flow (`feature/E4-65-sprints-and-backlog`)[cite: 2, 3].



## 2. Enlaces / Historial de Chats
Chat 1 (Planificación del Sprint 2 - Ticket E4-129): https://gemini.google.com/app/498ccb25c1229ac6?hl=es_419

## 3. Prompts Destacados y Soluciones

> Prompt principal 2:"Fatal: unable to auto-detect email address (got 'edube@Diana.(none)')"
>
> Resultado / Impacto: Se solucionó la falla de firma de commits configurando la identidad global del autor en Git mediante `git config --global user.email` y `user.name`, permitiendo concretar los commits vinculados a Jira de manera exitosa.

> Prompt principal 3:"¿Cómo implemento la creación de Sprints con fecha de inicio y fin dentro de mi archivo `apps/proyectos/models.py` sin sobreescribir el modelo `Proyecto` existente?"
>
> Resultado / Impacto: Se agregaron las clases `Sprint` y `UserStory` vinculadas por *Foreign Keys*, incluyendo el cálculo automático de duración en días mediante la sobreescritura del método `save()` y su registro en `admin.py`.