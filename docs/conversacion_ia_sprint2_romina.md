# Registro de Conversación con IA (CHIA) - Sprint 2

**Integrante:** Romina
**Proyecto:** GlobalExchange
**Rama:** `feature/SCRUM-tasas-simulador`
**Fecha:** Septiembre 2026

**URL del chat** = https://share.gemini.google/aCp2kKKIKNPY

## 1. Objetivos del Asistente
- Implementar la vista pública de tasas de cambio (`/api/divisas/tasas/`).
- Implementar el simulador de conversión (`/api/divisas/simular/`).
- Ajustar el formateador dinámico de decimales en el modelo `TasaCambio`.
- Integrar pruebas unitarias en `divisas/tests.py` manteniendo el resultado `OK` en `manage.py test`.

## 2. Puntos Clave Trabajados
1. **Modelos y Serializadores:**
   - Creación de `SimulacionRequestSerializer` con validaciones de tipo y monto positivo.
   - Ajuste de `min_value` a `Decimal('0.01')` para evitar advertencias de DRF.
   - Implementación de `_formatear_valor` en `TasaCambio` para mejorar la visualización en la UI/Admin sin alterar la precisión decimal en BD.

2. **Vistas y Permisos:**
   - Declaración de `permission_classes = [AllowAny]` para permitir acceso público en la pantalla de tasas y simulador.

3. **Control de Versiones y Pruebas:**
   - Resolución de conflictos en el merge con la rama `develop`.
   - Verificación de ejecuciones exitosas de la suite de pruebas unitarias (`OK`).