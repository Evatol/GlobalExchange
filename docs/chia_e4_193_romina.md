# Documentación de Asistencia de IA (CHIA) - Tarea E4-193: Ingresar a la terminal

**Fecha:** Octubre de 2026
**Proyecto:** Global Exchange - Sistema Casa de Cambios (IS2)
**Rama:** `feature/E4-193-ingresar-a-la-terminal`
**Link:** https://share.gemini.google/oQwhMKdkhHz3c
---

## 1. Resumen de la Interacción y Consultas
Durante el desarrollo de la tarea **E4-193**, se consultó y estructuró junto con el asistente de IA el flujo completo de autenticación y restricciones de negocio para la terminal de autoservicio:
1. Definición del mecanismo de bloqueo de negocio independiente de Keycloak para el modelo `Usuario`.
2. Implementación del modo Kiosco (anónimo para tasas y simulaciones) frente al uso autenticado.
3. Validación estricta de roles, estados, bloqueos y selección de cliente activo en el backend.
4. Integración de las pruebas unitarias enfocadas y compilación de la documentación técnica.

---

## 2. Decisiones de Diseño y Arquitectura Adoptadas con la IA

* **Separación de Responsabilidades (Keycloak vs. GlobalExchange):**
  Se decidió que Keycloak mantenga su rol exclusivo de autenticación de credenciales, mientras que el control de negocio de la aplicación (`GlobalExchange`) maneje un campo independiente de bloqueo (`Usuario.bloqueado`). Esto permite que, si un usuario está bloqueado, la aplicación pueda interceptar la petición y retornar de forma controlada el código HTTP `403` con un mensaje explicativo claro en pantalla, en lugar de impedir el inicio de sesión desde Keycloak.

* **Modo Kiosco y Restricciones:**
  Se configuró el comportamiento para que los usuarios anónimos puedan consultar tasas y realizar simulaciones de conversión libremente (sin registrar compras ni ventas reales). Para operar, el sistema exige obligatoriamente el flujo de Keycloak, validando el rol `usuario_final`, el perfil activo/desbloqueado y la presencia de clientes asociados.

* **Selección de Cliente Activo:**
  Se reutilizaron las funciones de sesión (`sesion.py`) para gestionar cuando un usuario posee múltiples clientes asociados, permitiendo mostrar un selector y validando en el servidor que el cliente seleccionado pertenezca al usuario y esté activo.

---

## 3. Archivos principales
* `apps/usuarios/models.py` y `apps/usuarios/migrations/0006_usuario_bloqueado.py`: campo de bloqueo independiente del estado activo.
* `apps/usuarios/sesion.py`: autorización de usuario final, estado del perfil y clientes disponibles.
* `apps/usuarios/views.py` y `apps/usuarios/templates/usuarios/gestion_roles.html`: administración de bloqueo solo por POST de administrador.
* `apps/caja/views.py` y `apps/caja/templates/caja/terminal_kiosco.html`: kiosco público vinculado a la operatividad de terminal.
* `apps/transacciones/views.py`: validación de autorización antes de crear operaciones.
* `apps/caja/test_terminales.py`, `apps/usuarios/tests.py` y `apps/transacciones/tests.py`: pruebas de flujo y permisos.
* `docs/caja.rst` y `docs/usuarios.rst`: documentación técnica Sphinx.

---

## 4. Pruebas y Validación Realizada
* Después de los últimos ajustes se ejecutaron y pasaron 402 pruebas combinadas de caja, usuarios y transacciones.
* También pasaron 156 pruebas enfocadas de terminales y transacciones digitales, incluyendo el control de bloqueo desde la API del kiosco y la preservación del flujo de operación fuera de terminal.
* Se validaron las consistencias con `manage.py check` y `makemigrations --check`.
* Se aplicó localmente la migración aditiva `0006_usuario_bloqueado.py`.
* Se compiló correctamente la documentación Sphinx de la aplicación.

## 5. Integración de ramas
La rama E4-193 incorpora localmente la rama `feature/E4-192-administrar-terminales`, necesaria para desarrollar y probar el kiosco sobre una terminal existente. La integración quedó registrada en el commit de merge `8847479`; no se publicó a GitHub ni se integró a `develop` al momento de esta documentación.