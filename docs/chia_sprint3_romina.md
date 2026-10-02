# Registro de Conversaciones con IA (CHIA) - Sprint 3

* **Integrante:** #3 Romina (Módulo de Transacciones y Lógica de Negocio)
* **Rol / Epic:** Gestión de Transacciones / Cancelación automática por cambio de cotización (E4-28)
* **Fecha:** Septiembre 2026

---

## 1. Resumen de Interacciones
Consultas a la Inteligencia Artificial para el desarrollo e implementación de la validación automática en el modelo `Transaccion` (`apps/transacciones/models.py`), asegurando que al confirmar una transacción se compare la `tasa_cambio` guardada frente a la cotización activa vigente (`TasaCambio`). Soporte en la corrección de atributos de modelos relacionados (`Usuario`, `Cliente`, `Moneda`), creación de pruebas unitarias (`TransaccionTasaCambioTestCase` en `apps/transacciones/tests.py`), y control de versiones con Git/GitHub en la rama correspondiente.

## 2. Enlaces / Historial de Chats
* Chat de Asistencia (E4-28): [https://share.gemini.google/0TdC6nkWS2qm]

## 3. Prompts Destacados y Soluciones
> **Prompt principal:** "Al confirmar el pago de una transacción PENDIENTE, comparar la tasa_cambio guardada contra la cotización activa actual de esa moneda y cancelar automáticamente si cambió."
>
> **Resultado / Impacto:** Se implementó exitosamente la lógica de negocio en el método `confirmar()`, lanzando una `ValidationError` y actualizando el estado a `CANCELADA` en caso de discrepancia. Se validó su correcto funcionamiento mediante pruebas unitarias en Django con resultado exitoso (`OK`).