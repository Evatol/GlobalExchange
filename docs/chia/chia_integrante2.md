Registro de Conversaciones con IA (CHIA) - Sprint 1

*Integrante: Angel Lovera (Integrante 2)
*Rol / Epic: Epic 2 - Gestión de Clientes y Asignación
*Fecha: Agosto 2026

---

## 1. Resumen de Interacciones

Consultas a la IA (Claude y Claude Code) para implementar el modelo Cliente con segmentación y su CRUD completo (E4-125/E4-124), coordinar e integrar mediante GitFlow y Pull Requests el trabajo de los 4 integrantes del equipo a la rama develop resolviendo conflictos de merge reales, corregir errores de configuración detectados durante las pruebas, y validar el sistema completo de punta a punta (Keycloak + Django + CRUD de Clientes).

## 2. Enlaces / Historial de Chats

Conversación de planificación y coordinación (Claude, chat): https://claude.ai/code/session_01RBzpSEukGkkE9bqjbr5AuH
Sesión de implementación (Claude Code): https://claude.ai/code/session_01RBzpSEukGkkE9bqjbr5AuH

## 3. Prompts Destacados y Soluciones

> Prompt principal: "Necesito implementar dos historias de Jira juntas: E4-125 (CRUD completo de Clientes con segmentación de datos) y E4-124 (pruebas unitarias del módulo de Clientes) [...] Usá plan mode para mostrarme los cambios antes de aplicarlos."
>
> Resultado / Impacto: Se implementó el modelo Cliente (tipo, categoría, límites de compra/venta, preferencia de tipo de cambio, según RF40-RF42 del ERS), su CRUD completo vía Django REST Framework, y 18 tests unitarios. La IA detectó que ya existía un modelo Cliente en `apps/usuarios` de otra rama en curso y consultó antes de duplicarlo — se decidió extenderlo en vez de crear una app nueva.

> Prompt principal: "Necesito que resuelvas un conflicto de merge entre dos ramas [...] usamos GitFlow con Pull Requests en GitHub [...] vos resolvés el conflicto localmente, pero el merge final a develop lo hago yo desde el botón de GitHub."
>
> Resultado / Impacto: Se resolvieron conflictos reales en `config/settings.py` (bloques de DRF y Keycloak/OIDC) y en `apps/usuarios/urls.py` (router del CRUD de Clientes vs. ruta del Menú Principal), combinando ambas funcionalidades sin pérdida de código de ningún integrante. Se aplicó este proceso en las 7 ramas del equipo integradas a develop.

> Prompt principal: "¿Por qué la ruta del menú devuelve 404 al intentar acceder sin sesión iniciada?"
>
> Resultado / Impacto: Se diagnosticó que faltaba `LOGIN_URL` en `settings.py` (Django usaba el valor por defecto `/accounts/login/`, inexistente en el proyecto). Se corrigió apuntándolo a `/oidc/authenticate/`, habilitando el flujo real de login vía Keycloak — confirmado con una prueba end-to-end completa (login → Menú Principal → creación de cliente real).