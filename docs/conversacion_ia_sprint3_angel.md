# Registro de Conversación con IA (CHIA) - Sprint 3

**Integrante:** Angel Lovera (Integrante 2)
**Rol / Epic:** Configuración y Administración del Sistema / Sprint 3 - AMB (Ambiente de Producción Montado)
**Herramienta:** Claude Code (CLI)
**Ramas:** `feature/E5-roles-negocio-keycloak`
**Fecha:** Septiembre 2026

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

## 7. Archivos / evidencia

- `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml`, `.dockerignore` — stack de desarrollo dockerizado.
- `apps/usuarios/management/commands/configure_keycloak_realm.py`, `seed_usuarios_demo.py` — bootstrap de Keycloak desde cero.
- `config/settings.py` — separación `KEYCLOAK_SERVER_URL` / `KEYCLOAK_PUBLIC_URL`.
- `.gitattributes`, `Dockerfile` (normalización CRLF) — fix del bug de Windows.
- `docker-compose.yml` (`KC_HOSTNAME`) — fix del 401 por issuer inconsistente.
- `docker-compose.prod.yml`, `config/settings.py` (`STATIC_ROOT`, `STORAGES`), `requirements.txt` (`gunicorn`, `whitenoise`) — AMB (E4-146).
- `COMO_EJECUTAR.txt` (Parte G, G.5) — guía paso a paso del equipo y del ambiente de producción.
