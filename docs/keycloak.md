# Keycloak — configuración como código (E4-120 / E4-37)

El realm de Keycloak **no se configura a mano**: hay management commands
idempotentes que aplican todo vía la API admin (`python-keycloak`). Reutilizan
el patrón de conexión de `apps/usuarios/services.py` y las credenciales admin de
`config/settings.py` (`KEYCLOAK_*`).

## Contenedor

Keycloak corre en Docker (imagen `quay.io/keycloak/keycloak:latest`, modo
`start-dev`), contenedor `keycloak-dev`, puerto `8080`. Consola: `http://localhost:8080/`
(admin / admin).

> **DNS del contenedor (necesario para el SMTP).** En la red bridge por defecto,
> el contenedor no resuelve `smtp.gmail.com` porque el host usa `systemd-resolved`
> (127.0.0.53) y Docker descarta los nameservers loopback. Solución: crear
> `/etc/docker/daemon.json` con
> `{ "dns": ["192.168.1.1", "8.8.8.8"] }`, `sudo systemctl restart docker` y
> `sudo docker start keycloak-dev`.

## Comandos

Correr desde la raíz del proyecto (`venv/bin/python manage.py <comando>`).
Todos aceptan `--dry-run`.

| Comando | Qué configura |
|---|---|
| `configure_keycloak_registration` | Autoregistro (`registrationAllowed`), verificación de correo (`verifyEmail`), recuperación de contraseña (`resetPasswordAllowed`), bloqueo por intentos fallidos (`bruteForceProtected`) y el **SMTP** del realm. Pide el App Password de Gmail por consola / env `KEYCLOAK_SMTP_PASSWORD`. |
| `configure_keycloak_roles` | Mapper en el cliente OIDC: los **roles de realm** del usuario van en el claim `roles` (userinfo + id token). Django los sincroniza en grupos y permisos (`CustomOIDCBackend._sync_roles`). |
| `configure_keycloak_logout` | `post logout redirect URIs` del cliente OIDC, para el logout RP-initiated. |
| `configure_keycloak_locale` | Realm en **español** (pantallas y correos). |

Orden sugerido en un realm nuevo:

```
venv/bin/python manage.py configure_keycloak_registration
venv/bin/python manage.py configure_keycloak_roles
venv/bin/python manage.py configure_keycloak_logout
venv/bin/python manage.py configure_keycloak_locale
```

## Alta de usuario por el administrador (RF1-RF3)

Distinto del autoregistro: acá el **admin** crea la cuenta.

```
venv/bin/python manage.py crear_usuario_keycloak <username> <email> --rol cajero
venv/bin/python manage.py crear_usuario_keycloak jperez jperez@x.com --nombre Juan --apellido Perez --rol analista
```

Crea el usuario en Keycloak con una **contraseña aleatoria** (`secrets`, `temporary=true`),
le asigna un **rol de realm** y **envía la contraseña por correo** (`services.enviar_credenciales_por_correo`).
En desarrollo el correo se imprime en la terminal (backend de consola); en producción se
setea `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` y `EMAIL_HOST_PASSWORD`
por variable de entorno.

Flags: `--no-email` (no envía), `--mostrar-password` (imprime la clave en pantalla).

## Qué queda en manos de Keycloak (E4-120)

- Pantallas de login y registro (no hay formularios propios en Django).
- Verificación de correo, recuperación de contraseña, bloqueo por fuerza bruta.
- Emisión y firma de tokens (OIDC / RS256). Django valida contra el JWKS.
- Roles de realm → se reflejan en Django vía el claim `roles` en cada login.

## Qué queda en Django

- Validar el token/sesión antes de servir rutas protegidas (`mozilla-django-oidc`
  + `@login_required`).
- Espejar el usuario localmente en el primer login (`CustomOIDCBackend`).
- Mapear roles de Keycloak → `Group` de Django + `is_staff`/`is_superuser`
  (rol `admin`/`administrador`). Configurable con `OIDC_ROLES_CLAIM`,
  `OIDC_ADMIN_ROLES`, `OIDC_IGNORED_ROLES`.
- Logout: `apps/usuarios/oidc.py::provider_logout_url` cierra también la sesión SSO.

## Pendiente

- Export del realm versionado (`realm-export.json`) o `docker-compose` con el
  realm importado al arrancar, para no depender de los comandos en un entorno
  desde cero. Los comandos cubren la config; falta el bootstrap del contenedor.
- Endpoints de OIDC apuntan a `localhost:8080` (hardcodeados en settings); pasar
  a variables de entorno para producción.
