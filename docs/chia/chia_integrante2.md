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

---

## 4. Anexo Sprint 1 — Autoregistro con verificación de correo (E4-120 / E4-37)

**Cambio de requerimiento** (pedido por la profesora): se reincorpora el
autoregistro público de usuarios, ahora **con verificación de correo obligatoria**,
usando las funciones **nativas de Keycloak** (sin formulario propio en Django).

### Enlace del chat
Sesión de implementación (Claude Code): https://claude.ai/code/session_01RBzpSEukGkkE9bqjbr5AuH

### Prompts destacados y soluciones

> Prompt principal: "Quiero implementar autoregistro de usuarios con verificación de
> correo usando las funciones NATIVAS de Keycloak (no un formulario propio en Django).
> Investigá primero cómo está gestionado hoy el realm [...] elegí el método más prolijo
> y versionable."
>
> Resultado / Impacto: La IA detectó que **no existía configuración como código** del
> realm (todo a mano en la consola web). Se crearon 3 management commands idempotentes
> (`configure_keycloak_registration`, `configure_keycloak_logout`,
> `configure_keycloak_locale`) que aplican la config vía la API admin de Keycloak
> (`python-keycloak`), reutilizando el patrón de `apps/usuarios/services.py`. El App
> Password de Gmail se pide por consola / variable de entorno, nunca se commitea.

> Diagnóstico guiado: "Me registro pero no llega el correo de verificación."
>
> Resultado / Impacto: Se rastreó el error real en los logs del contenedor de Keycloak
> (`UnknownHostException: smtp.gmail.com`). Causa: el contenedor en la red bridge de
> Docker no resolvía DNS porque el host usa `systemd-resolved` (127.0.0.53) y Docker
> descarta los nameservers loopback. Solución: `/etc/docker/daemon.json` con DNS
> explícito. Luego apareció `534-5.7.9 Application-specific password required` — se había
> tipeado la contraseña normal de Gmail en vez del App Password de 16 caracteres.

> Prompt principal: "Al cerrar sesión me lleva de nuevo al login admin de Django, no
> debería llevarme al login de Keycloak?"
>
> Resultado / Impacto: El botón "Cerrar Sesión" apuntaba a `/admin/logout/` (solo
> cerraba la sesión de Django, no la SSO de Keycloak). Se implementó **logout OIDC
> real**: `apps/usuarios/oidc.py::provider_logout_url` + `OIDC_OP_LOGOUT_ENDPOINT` /
> `OIDC_OP_LOGOUT_URL_METHOD` en settings + formulario POST a `{% url 'oidc_logout' %}`
> en el template. Ahora cierra ambas sesiones y vuelve al login de Keycloak.

> Consulta: "En Keycloak 26 el registro no pide contraseña y después obliga a
> 'Update password'. ¿Es un bug?"
>
> Resultado / Impacto: No es bug. Se verificó (probando con `verifyEmail` on/off) que
> Keycloak 26.7 **omite a propósito** el campo de contraseña en el registro cuando la
> verificación de correo está activa: crea la cuenta sin credencial y la contraseña se
> define recién después de verificar el correo (evita cuentas con credenciales sobre
> emails no verificados). El flujo cumple el requerimiento. Se puso además el realm en
> **español** (UI + emails) con `configure_keycloak_locale`.

### Archivos / evidencia
- `apps/usuarios/management/commands/configure_keycloak_*.py` — configuración de Keycloak como código.
- `apps/usuarios/oidc.py`, `config/settings.py`, `apps/usuarios/templates/usuarios/menu_principal.html` — logout OIDC.
- `COMO_EJECUTAR.txt` — guía de ejecución paso a paso (servicios, pruebas, troubleshooting).