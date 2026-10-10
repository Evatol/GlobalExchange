## Tarea E4-33 — Notificar cambios de cotización por correo (RF85)


## Identificación de la Tarea
- **Código:** E4-33
- **Título:** Notificar cambios de cotización por  correo
- **Autora:** Romina Araceli Pérez Gaona
- **Link:** https://share.gemini.google/mi2mBgxwxJyE


### Implementación
Se amplió `procesar_cambio_cotizacion` en `apps/divisas/services.py`.
Cuando existe una cotización anterior y la variación supera el umbral configurado,
el servicio busca usuarios que tengan la moneda modificada entre sus favoritas.
Por cada usuario con dirección de correo, crea una notificación interna y programa
un correo mediante `transaction.on_commit`, para que el envío ocurra después de
confirmar la transacción de base de datos.

El correo incluye la moneda y los detalles de las tasas de compra y/o venta que
superaron el umbral: valores anterior y nuevo, dirección del cambio y porcentaje.
Si el envío falla, se captura el error y se imprime una advertencia; la cotización
ya guardada no se revierte.

### Archivos relacionados
- `apps/divisas/services.py`: cálculo de variaciones, selección de destinatarios,
  notificación interna y envío de correo.
- `apps/divisas/views.py`: invocación del servicio desde las rutas de escritura
  de cotizaciones.
- `config/settings.py`: configuración del backend de correo de Django.
- `apps/notificaciones/tests.py`: pruebas de destinatarios, contenido básico del
  correo, variación bajo el umbral y ausencia de favoritos.

### Verificación
Comando ejecutado:
`venv\Scripts\python manage.py test apps.notificaciones`

Resultado: 4 pruebas pasaron.

En las pruebas se utiliza el backend de correo en memoria de Django (`mail.outbox`).
En desarrollo, la configuración predeterminada imprime los mensajes en la consola.