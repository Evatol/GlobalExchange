# Registro de Conversación con IA (CHIA) - Sprint 3

**Integrante:** Angel Lovera (Integrante 2)
**Rol / Epic:** Configuración y Administración del Sistema / Sprint 3 - AMB (E4-146), límites por cliente (E4-143), CHIA (E4-148)
**Herramienta:** Claude Code (CLI)
**Ramas:** `feature/E5-roles-negocio-keycloak`, `fix/E4-19-20-144-completar`, `fix/E4-28-completar`, `fix/E4-104-agregar-tests`, `feat/E4-143-limites-cliente`, `fix/puerto-postgres-sin-publicar`, `feature/E4-28-script-demo-cancelacion`
**Fecha:** Septiembre - Octubre 2026

---

## 1. Resumen de Interacciones

El foco de mi parte del Sprint 3 fue **E4-146 (AMB)**, pero para llegar
ahí primero hizo falta resolver un problema real: el equipo no tenía
forma sencilla de correr el sistema completo (Django + Postgres +
Keycloak con roles ya configurados) para poder probar y desarrollar sobre
la misma base. Uso la IA para: (a) dockerizar todo el stack desde cero,
(b) diagnosticar y corregir dos bugs reales que aparecieron recién al
probarlo en la máquina de un compañero (no en la mía), y (c) armar el
ambiente de "producción" (AMB) sobre esa misma base. En paralelo, usé la
IA para analizar el ERS y la guía de la cátedra y organizar el Sprint 3
en Jira.

En la segunda mitad del sprint la IA se usó para verificar el trabajo del
equipo antes de darlo por terminado (secciones 7 y 12), implementar mi
historia de límites por cliente (E4-143) y revisar el alcance completo
antes de la presentación, donde aparecieron y se corrigieron errores que
los tests no detectaban (sección 11).

## 2. Dockerización completa del stack

> Prompt: "¿no sería bueno dockerizar todo así lo pueden correr sin
> ningún problema, o igual tendrían problemas con el Keycloak por
> ejemplo?"
>
> Resultado / Impacto: se identificó el problema real antes de escribir
> código: la configuración de Keycloak (realm, roles, cliente OIDC) solo
> existía clickeada a mano en mi consola, no en el repo — dockerizar sin
> resolver eso dejaría a cada compañero con un Keycloak vacío. Se creó
> `apps/usuarios/management/commands/configure_keycloak_realm.py`
> (bootstrap idempotente: crea el realm y el cliente OIDC si no existen,
> reutilizando los comandos `configure_keycloak_*` ya existentes de
> sprints anteriores) y `seed_usuarios_demo.py` (crea `admin_demo` /
> `analista_demo` / `cliente_demo` con contraseña fija, uno por rol). Se
> separó `KEYCLOAK_SERVER_URL` (uso interno de Django dentro del
> contenedor) de `KEYCLOAK_PUBLIC_URL` (a la que redirige el navegador),
> porque Docker hace que Django y el navegador vean a Keycloak por
> nombres distintos. `Dockerfile` + `docker-entrypoint.sh` +
> `docker-compose.yml` nuevos. Verificado de punta a punta levantando un
> Keycloak completamente vacío en un stack descartable y confirmando el
> bootstrap automático completo.

## 3. Bug real en Windows: CRLF rompía el contenedor

> Prompt (reportado por un compañero probando en Windows): `docker
> compose up --build` fallaba con `exec
> /usr/local/bin/docker-entrypoint.sh: no such file or directory`.
>
> Resultado / Impacto: se diagnosticó como un problema clásico de línea
> de comandos en Windows — Git ahí convierte los `.sh` a CRLF al clonar
> (`core.autocrlf=true`), lo que rompe el shebang `#!/bin/sh`. Se
> verificó forzando CRLF a propósito en una copia del script y
> reproduciendo el error exacto. Arreglo en dos capas: `.gitattributes`
> (fuerza `*.sh` a LF en cualquier clon futuro) y un `sed` en el
> `Dockerfile` que normaliza el archivo al armar la imagen, para que
> funcione ya mismo con un `git pull` sin que nadie tenga que tocar su
> configuración de Git.

## 4. Bug real en Docker: 401 al loguearse (issuer de Keycloak)

> Prompt (reportado por el mismo compañero, ya con el fix anterior):
> el login llegaba hasta `/oidc/callback/` y ahí explotaba con `401
> Unauthorized` al pedir `/userinfo`.
>
> Resultado / Impacto: se diagnosticó que, sin un hostname fijo,
> Keycloak calcula el "issuer" de cada token según el `Host` de *cada
> pedido por separado* — el navegador le habla por `localhost:8080`
> pero Django, adentro del contenedor, por `keycloak:8080`: dos
> issuers distintos para la misma sesión, y Keycloak rechaza el token al
> validarlo desde el otro contexto. Se corrigió fijando `KC_HOSTNAME` en
> el servicio de Keycloak. Verificado comparando el "issuer" del
> discovery document pedido desde el host vs. desde adentro del
> contenedor `web` (antes daban distinto, después igual), y confirmando
> con un token real que `/userinfo` responde 200 con el rol ya
> sincronizado.

## 5. Organización del Sprint 3 en Jira

> Prompt: análisis completo del ERS (`EQUIPO_03_A_ERS_01.pdf`) y de la
> guía de la cátedra contra el estado real del código, para repartir el
> Sprint 3 entre el equipo.
>
> Resultado / Impacto: se mapeó cada punto del alcance del Hito 5
> (operación de compra/venta con comisión, cancelación por cambio de
> cotización, historial de transacciones) contra los RF del ERS y contra
> historias ya cargadas en Jira, evitando crear duplicados. Se detectó y
> corrigió un desbalance real (una historia obligatoria del sprint,
> "historial de transacciones", había quedado fuera del Sprint 3 y sin
> asignar) y un ticket duplicado (`Ambiente de Producción Montado`
> cargado dos veces). También se acompañó la resolución de un error real
> de un bulk-edit en Jira que dejó historias con el campo Sprint y
> Asignado inconsistentes, verificando el estado real antes de dar por
> buena cada corrección.

## 6. AMB - Ambiente de Producción Montado (E4-146)

> Prompt: "arranquemos por AMB — 100% independiente, no depende del
> código de Transacciones que van a escribir los demás."
>
> Resultado / Impacto: se armó `docker-compose.prod.yml` (aparte del de
> desarrollo): `DEBUG=False`, `gunicorn` en vez de `runserver`, estáticos
> servidos por WhiteNoise (`STATIC_ROOT` + `STORAGES` nuevos en
> `settings.py`, `collectstatic` automático en el entrypoint cuando
> `DEBUG=False`). Se decidió explícitamente no simular HTTPS real (sin
> dominio ni certificado no tiene sentido fingirlo) y se documentó esa
> limitación en el propio compose y en `COMO_EJECUTAR.txt`. Verificado de
> punta a punta en un stack descartable: `collectstatic` corrió (154
> archivos), gunicorn levantó con 3 workers, el CSS del admin se sirvió
> sin `runserver`, y el login completo (Keycloak → token → `/userinfo`
> con rol sincronizado) funcionó igual que en desarrollo.

## 7. Verificar el trabajo del equipo antes de darlo por terminado

> Prompt: "Me dijo Edu que ya terminó, ¿puedes verificarlo?" (y lo mismo
> para Eva y Romina).
>
> Resultado / Impacto: en vez de confiar en el "ya está", se revisó cada
> rama en una copia aislada (`git worktree`, base de datos y stack de
> Docker descartables) contra el código real. Se encontró que el PR #28
> (compra/venta) se había mergeado a `develop` **sin funcionar**: sus
> vistas no tenían URL (se comprobó con `NoReverseMatch`), faltaba el
> template, no existía la venta, no tenía tests y la comisión era plana.
> Además crasheaba al operar con `ValueError: Cannot assign "<User>":
> "Transaccion.usuario" must be a "Usuario" instance`, porque usaba el
> usuario de autenticación de Django en lugar del usuario de negocio. Se
> completó en `fix/E4-19-20-144-completar` (vista compartida por la
> pantalla y la API, venta, comisión según la categoría del cliente y
> tests). A los PR de Eva (historial, E4-104/E4-36) y Romina (cancelación,
> E4-28) les faltaban tests, y se agregaron. También se corrigió un test
> que fallaba solo en el CI porque, al seguir una redirección, terminaba
> llamando a un Keycloak real que en el CI no existe.

## 8. Límites de compra y venta por cliente (E4-143)

> Prompt: "Sigue con esto E4-143".
>
> Resultado / Impacto: `Transaccion.validar_limite_cliente()` compara el
> total de la operación (ya con la comisión) contra el límite de compra o
> de venta configurado en el CRUD de Clientes. Un límite en 0 significa
> "sin límite", que es el valor por defecto de todo cliente existente:
> así no se rompió ningún cliente cargado antes. La validación ocurre
> antes de guardar, para que una operación rechazada no quede registrada.
> 6 tests, incluido el mismo control en el endpoint de la API.

## 9. Montos con 8 decimales en pantalla

> Prompt (captura de pantalla): una compra de 9,26 USD mostraba un total
> de `67935.99000000`.
>
> Resultado / Impacto: la tasa se guarda con 6 decimales y el cálculo
> intermedio arrastraba esa precisión hasta el total que se mostraba,
> aunque en la base quedara bien. Se agregó `_a_guaranies()`, que redondea
> a 2 decimales con `ROUND_HALF_UP`, y un test que verifica que todos los
> montos tengan exactamente 2 decimales. Mientras escribía ese test, el
> valor esperado que propuso la IA estaba mal calculado (`68612.97` en
> vez de `68611.97`); el test lo detectó y se corrigió antes del commit.

## 10. Un solo comando para levantar todo

> Prompt: "¿No podemos crear un script completo para arrancar todo el
> sistema?"
>
> Resultado / Impacto: `scripts/levantar_sistema.sh` verifica Docker y
> los puertos, levanta el stack, espera a que responda y carga los datos
> de demostración (`seed_datos_demo`: monedas, cotizaciones, clientes de
> distinta categoría y la asociación de `cliente_demo`). En el camino
> salieron tres problemas reales: el puerto de Postgres chocaba con el
> PostgreSQL local de cada uno (se dejó de publicar, porque Django usa la
> red interna de Docker); el enlace "Registrarse" no aparecía porque el
> bootstrap creaba el realm sin autoregistro; y para la verificación por
> correo hacía falta el App Password de Gmail. Antes de hardcodearlo, se
> comprobó con la API de GitHub que **el repositorio es público**, así
> que el password quedó fuera del repo: cada integrante lo pone en su
> `.env` (ignorado por git) y lo activa con `--con-correo`.

## 11. Revisión del sprint antes de la presentación

> Prompt: "Analiza esto que se pidió si ya está completo como para
> entregar" (los tres ítems del alcance del Hito 5).
>
> Resultado / Impacto: probando con login real y operaciones reales
> aparecieron tres problemas que los tests no detectaban, porque los
> tests fijaban el comportamiento equivocado:
>
> - **Las tasas se aplicaban al revés.** El cliente compraba dólares a la
>   tasa de *compra* de la casa (7.300) y los vendía a la de *venta*
>   (7.400). La prueba de que estaba mal: comprar y vender 13 USD seguido
>   le dejaba al cliente 344,50 Gs de ganancia. La regla estaba copiada
>   en 7 lugares; se centralizó en `TasaCambio.tasa_para()` y todos pasaron
>   a usarla. Importaba especialmente en `confirmar()`, que si usara una
>   regla distinta a la de la creación cancelaría todas las operaciones.
> - **La cancelación por cambio de cotización (E4-28) no se podía ver en
>   pantalla**, porque la operación se confirmaba al crearse y nunca
>   existía un "antes del pago". La idea de agregar un botón "Confirmar
>   pago" fue mía; con la IA se implementó: la operación queda pendiente,
>   un resumen muestra tasa, subtotal, comisión y total, y al confirmar se
>   vuelve a leer la cotización. El botón "Cancelar operación" cubre de
>   paso el RF23.
> - **Una transacción cancelada podía volver a confirmarse** si la
>   cotización regresaba a su valor original. Se agregó la guarda de
>   estado y su test.
>
> También se corrigió la vista previa de la API (cobraba siempre la
> comisión estándar), el mensaje de medio de pago repetido (mostraba los
> nombres internos de los campos), y la API pasó a estar cerrada por
> defecto. Para el AMB se creó `scripts/verificar_produccion.sh`, que
> comprueba en un comando lo que distingue producción de desarrollo.

## 12. Git Flow: errores propios y cómo se corrigieron

> Prompt: "¿Está bien?" (después de crear el tag del Sprint 3).
>
> Resultado / Impacto: la IA detectó que el tag `v1.4.0` se había creado
> sobre un `main` al que todavía no había llegado `develop`, así que le
> faltaban los CHIA de dos integrantes. También que los PR #32, #35 y #36
> se habían abierto contra `main` en lugar de `develop`: GitHub propone
> `main` como base por defecto. Se corrigió sincronizando `develop` con
> un PR propio y llevando `develop` a `main` antes del tag. A partir de
> ahí, cada PR se revisa antes de abrirlo, para confirmar que la base sea
> `develop`.

## 13. Archivos / evidencia

- `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml`, `.dockerignore` — stack de desarrollo dockerizado.
- `apps/usuarios/management/commands/configure_keycloak_realm.py`, `seed_usuarios_demo.py` — bootstrap de Keycloak desde cero.
- `config/settings.py` — separación `KEYCLOAK_SERVER_URL` / `KEYCLOAK_PUBLIC_URL`.
- `.gitattributes`, `Dockerfile` (normalización CRLF) — fix del bug de Windows.
- `docker-compose.yml` (`KC_HOSTNAME`) — fix del 401 por issuer inconsistente.
- `docker-compose.prod.yml`, `config/settings.py` (`STATIC_ROOT`, `STORAGES`), `requirements.txt` (`gunicorn`, `whitenoise`) — AMB (E4-146).
- `COMO_EJECUTAR.txt` (Parte G, G.5) — guía paso a paso del equipo y del ambiente de producción.
- `apps/transacciones/views.py` (`_crear_transaccion_digital`), `templates/transacciones/operar_divisa.html` — compra/venta completada (E4-19/E4-20/E4-144).
- `apps/transacciones/models.py` (`validar_limite_cliente`, `_a_guaranies`) — límites por cliente (E4-143) y redondeo.
- `scripts/levantar_sistema.sh`, `apps/usuarios/management/commands/seed_datos_demo.py` — arranque en un comando con datos de demostración.
- `apps/divisas/models.py` (`TasaCambio.tasa_para`) — tasas aplicadas como en una casa de cambio real.
- `apps/transacciones/templates/transacciones/operacion_detalle.html`, vistas `operacion_*` — confirmación de pago (E4-28) y cancelación por el cliente (RF23).
- `scripts/verificar_produccion.sh`, `docs/produccion.md` — verificación y documentación del AMB.
