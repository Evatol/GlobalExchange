# Documentación de Asistencia de IA (CHIA) - Tarea E4-24

* **Estudiante:** Romina Araceli Pérez Gaona
* **Fecha:** 09 de Octubre de 2026
* **Tarea:** E4-24 (Marcar monedas como favoritas)
* **Link:** https://share.gemini.google/boi0Bj28nLDL

## Resumen del trabajo asistido
Se utilizó la asistencia de la IA para:
1. Diseñar la relación de base de datos (`ManyToManyField`) en el modelo `Usuario` vinculándolo con el modelo `Moneda` de la app `divisas`, aplicando la restricción de solo permitir monedas activas (`limit_choices_to={'estado': True}`).
2. Adaptar la vista `mi_perfil_view` en `apps/usuarios/views.py` para procesar la selección y almacenamiento persistente de las monedas favoritas mediante peticiones `POST` protegidas con CSRF.
3. Actualizar la plantilla HTML del perfil (`mi_perfil.html`) añadiendo la sección visual con casillas de verificación (`checkboxes`) para que el usuario gestione sus preferencias.
4. Escribir y validar las pruebas unitarias en `apps/usuarios/tests.py` para asegurar la persistencia y el correcto funcionamiento del modelo y la vista.