# Registro de Conversación con IA (CHIA) - Sprint 2

**Integrante:** Angel Lovera (Integrante 2)
**Rol / Epic:** Epic 2 - Gestión de Clientes / Sprint 2 - ALC (Monedas, Cotizaciones, Medios de Pago, Tasas, Simulador)
**Herramienta:** Claude Code (CLI)
**Ramas:** `feature/E4-130-selector-y-medios-pago-cliente`, `fix/E4-26-cotizaciones-crud`, `fix/SCRUM-vista-publica-cotizaciones`, `chore/E4-qa-docs-fixes`
**Fecha:** Septiembre 2026

---

## 1. Resumen de Interacciones

Trabajo con la IA (Claude Code) para: (a) implementar mi propia parte del
Sprint 2 (selector de cliente activo y CRUD de medios de pago del
cliente); (b) **verificar** —no solo confiar de palabra— el trabajo que
mis compañeros reportaban como terminado, revisando el código real antes
de darlo por bueno; y (c) cerrar los puntos de calidad (QA) y
documentación (PUD) del Hito 4. Esto incluyó encontrar y corregir dos
problemas serios en trabajo ya mergeado o por mergear de otros
integrantes, y coordinar cada corrección con ellos antes de aplicarla.

## 2. Mi parte: selector de cliente activo y medios de pago (E4-130 / RF43 / RF17)

> Prompt principal: implementar el selector de cliente activo (RF43, un
> usuario asociado a varios clientes puede elegir sobre cuál operar) y el
> CRUD de medios de pago del cliente (RF17), siguiendo el mismo patrón de
> borrado lógico que ya usa el CRUD de Monedas de Eva.
>
> Resultado / Impacto: se creó `apps/usuarios/sesion.py`
> (`clientes_disponibles`, `get_cliente_activo`, `set_cliente_activo`,
> selector basado en sesión) más un formulario en `menu_principal.html`;
> y en `apps/transacciones` los modelos `MetodoPago` (catálogo) y
> `MedioPagoCliente` (alias, identificador, titular, ligado a un
> cliente), con serializers, viewset y 19 tests nuevos. Probado
> manualmente en el navegador con datos de prueba antes de abrir el PR.

## 3. Verificación del trabajo de Eduardo: CRUD de Cotizaciones (E4-26)

> Prompt: "me dijo Edu que ya terminó, ¿podés verificarlo?"
>
> Resultado / Impacto: se le pidió a la IA revisar el commit real
> (`git show --stat`, diff completo, grep de referencias cruzadas,
> `manage.py test` en un worktree aislado) en vez de confiar en el
> reporte verbal. Se encontró que **no era un CRUD**: solo agregaba un
> modelo `Cotizacion` nuevo (con `moneda` como texto libre, sin FK) y su
> alta en el admin de Django — sin serializer, sin vista, sin URL y sin
> tests. Además duplicaba al `TasaCambio` que ya usaban Eva y Romina.
>
> Prompt de seguimiento: "Edu ya no tiene tiempo, arreglalo vos
> directamente."
>
> Resultado / Impacto: se eliminó el modelo duplicado y se reconstruyó
> el CRUD sobre `TasaCambio` (que ya tiene FK a `Moneda`): `CotizacionViewSet`
> en `/api/divisas/cotizaciones/`, con desactivación automática de la
> cotización anterior de una moneda al crear una nueva (una sola vigente
> por moneda), validación de que la venta no sea menor a la compra, y 9
> tests. Rama `fix/E4-26-cotizaciones-crud`, PR #14.

## 4. Revisión y corrección de la vista pública de Romina

> Prompt: "¿podemos probar antes de mergear?" / "corregilo vos
> directamente, punto por punto los problemas que encontraste."
>
> Resultado / Impacto: Romina había resuelto un problema real (la raíz
> del sitio no mostraba nada sin login, solo redirigía al admin de
> Django), pero el login/logout de su pantalla nueva iba al login propio
> de Django (`admin:login`/`admin:logout`) en vez de Keycloak, evitando
> por completo el autoregistro, la verificación de correo y la
> sincronización de roles del Hito 3. Se corrigió para que use las
> mismas rutas OIDC del panel principal, con `next` llevando al portal
> tras el login. También se encontró que duplicaba la lógica de cálculo
> del simulador (con un bug: una cantidad no numérica rompía la
> página); se centralizó en un método de manager compartido
> (`TasaCambio.objects.activa_para`) y en el mismo serializer de
> validación. Se agregaron 8 tests. Rama `fix/SCRUM-vista-publica-cotizaciones`,
> PR #16.
>
> Prueba manual guiada: se probó la rama en el navegador antes de
> mergear (login vía Keycloak, calculadora, logout). Se detectaron y
> corrigieron además el contraste de colores (texto casi invisible sobre
> el tema oscuro original) y que el logout volvía al login de Keycloak
> en vez de a la pantalla pública (`LOGOUT_REDIRECT_URL`).

## 5. QA y documentación (Hito 4)

> Prompt: análisis completo de qué faltaba para el Hito 4 contra la
> rúbrica (SCC/PUD/ALC/PLA/QA/CHIA).
>
> Resultado / Impacto: se encontraron y corrigieron tres pendientes
> reales: (1) `OIDC_RP_CLIENT_SECRET` y las credenciales admin de
> Keycloak estaban hardcodeadas en texto plano en `settings.py`, ahora se
> leen por variable de entorno; (2) faltaban tres módulos nuevos sin
> documentar en Sphinx (`divisas.serializers`, `transacciones.serializers`,
> `usuarios.sesion`); (3) el job de CI que compilaba la documentación
> estaba deshabilitado desde el Hito 3 por un crash en Python 3.13 nunca
> diagnosticado. Se reprodujo el crash en un contenedor Docker con esa
> versión de Python: autodoc llama a `repr()` sobre los `queryset` de los
> ViewSets (ej. `Moneda.objects.all()...`), lo que ejecuta una consulta
> SQL real; ese job nunca tuvo una base de datos disponible. Se agregó el
> mismo servicio de Postgres que ya usa el job de tests. Rama
> `chore/E4-qa-docs-fixes`, PR #17.

## 6. Archivos / evidencia

- `apps/usuarios/sesion.py`, `apps/usuarios/templates/usuarios/menu_principal.html` — selector de cliente activo (RF43).
- `apps/transacciones/models.py`, `serializers.py`, `views.py`, `urls.py` — CRUD de medios de pago del cliente (RF17).
- `apps/divisas/models.py` (`TasaCambioQuerySet.activa_para`), `views.py` (`CotizacionViewSet`) — CRUD de Cotizaciones reconstruido (E4-26).
- `apps/divisas/templates/divisas/publica.html`, `views.py` (`PantallaPublicaCambiosView`) — pantalla pública corregida.
- `config/settings.py`, `.env.example` — secretos de Keycloak por variable de entorno.
- `docs/divisas.rst`, `docs/transacciones.rst`, `docs/usuarios.rst`, `.github/workflows/ci.yml` — documentación y CI (PUD).
- `apps/divisas/tests.py`, `apps/transacciones/tests.py` — tests nuevos de este sprint (28 en total entre ambos módulos).
