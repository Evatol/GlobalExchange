# Documentación de Asistencia de IA (CHIA) - Tarea E4-32

## Identificación de la Tarea
- **Código:** E4-32
- **Título:** Notificaciones de variación de precios en tiempo real
- **Autora:** Romina Araceli Pérez Gaona
- **Link:** https://share.gemini.google/mi2mBgxwxJyE

## Resumen de Cambios Implementados
1. **Configuración de Umbral:** Se añadió la variable `PRICE_CHANGE_THRESHOLD_PERCENT` en `config/settings.py` (con un valor por defecto de `1.0` equivalente al 1%) y se documentó en `.env.example`.
2. **Capa de Servicio (`apps/divisas/services.py`):** Se creó la función `procesar_cambio_cotizacion` para evaluar de forma independiente las variaciones porcentuales de la tasa de compra y tasa de venta frente a la cotización activa anterior.
3. **Integración en Rutas de Escritura:** Se conectó el servicio de comparación en el `ViewSet` y en las vistas HTML tradicionales de gestión de cotizaciones (`gestion_cotizaciones_view`, `cotizacion_editar_view`, `cotizacion_toggle_view`).
4. **Endpoint de Notificaciones (`apps/notificaciones/views.py`):** Se implementó una vista protegida con `@login_required` que expone los avisos no leídos del usuario conectado, admitiendo el parámetro `?desde_id=` para optimizar el sondeo.
5. **Interfaz de Usuario:** Se actualizó `menu_principal.html` con un script de sondeo (*polling* cada 5 segundos) para mostrar alertas flotantes dinámicamente sin recargar la página.
6. **Pruebas Unitarias:** Se cubrieron los escenarios de umbrales menores al 1%, mayores al 1%, filtrado estricto por favoritos y seguridad de la API en `apps/notificaciones/tests.py`.