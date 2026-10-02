# Registro de Conversaciones con IA (CHIA) - Sprint 3

* **Integrante:** Eduardo Irala
* **Rol / Tarea:** Scrum Master / Operaciones Digitales de Divisas (tickets E4-19, E4-20, E4-144)
* **Fecha:** Octubre 2026

---

## 1. Resumen de Interacciones

Durante el desarrollo del Sprint 3 utilicé la Inteligencia Artificial para
sincronizar el entorno local mediante comandos de Git Flow (`git rebase`),
desarrollar la lógica financiera de tasas y comisiones en Django y construir los
endpoints para las operaciones de compra y venta digital de divisas.

* **Sincronización Git Flow:** actualización de la rama local `develop` mediante
  `git rebase origin/develop` para incorporar los cambios integrados por los
  compañeros sin generar conflictos.
* **Lógica financiera (E4-144):** implementación del método
  `calcular_tasas_y_comisiones()` en `apps/transacciones/models.py` y creación de
  la vista REST `CalcularTransaccionAPIView` para desglosar subtotal, comisiones
  y montos finales en tiempo real.
* **Operaciones de divisas (E4-19 y E4-20):** creación de las vistas de compra y
  venta en `apps/transacciones/views.py` para procesar transacciones obteniendo
  las cotizaciones activas de `apps/divisas` y aplicando la correspondiente
  deducción de comisiones.
* **Pruebas y calidad:** verificación de la suite de pruebas unitarias
  (`python manage.py test apps.transacciones`), con un resultado exitoso de 29
  tests aprobados al momento de la implementación.

## 2. Enlaces / Historial de Chats

* Chat 1 (sincronización Git, lógica de tasas/comisiones y operaciones
  digitales): https://gemini.google.com/app/5c0ba6e9c1cdeaab
