# Configuración de producción (AMB - Hito 3)

## Qué se configuró

- **Separación desarrollo / producción vía variables de entorno** usando
  `django-environ`. `config/settings.py` carga un archivo `.env` de la raíz
  del proyecto al arrancar.
- Variables externalizadas (con el valor de desarrollo como default, para no
  romper nada si el `.env` no existe):
  - `SECRET_KEY`
  - `DEBUG`
  - `ALLOWED_HOSTS`
  - Base de datos: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
    (el `ENGINE` sigue fijo en PostgreSQL).
- **Endurecimiento de seguridad condicionado a `DEBUG=False`** (bloque al
  final de `settings.py`): redirección a HTTPS, cookies de sesión/CSRF
  seguras, HSTS a 1 año y `SECURE_PROXY_SSL_HEADER` para operar detrás de un
  proxy inverso que termina TLS. En desarrollo (`DEBUG=True`) nada de esto se
  aplica, así el trabajo local sigue por HTTP sin fricción.
- `.env` está en `.gitignore` (no se versiona). `.env.example` documenta las
  variables disponibles.

## Cómo se validó

- `python manage.py check` y `python manage.py test` → sin cambios respecto
  de antes (18 tests OK; solo persisten los 3 warnings `models.W042`
  pre-existentes).
- Con `DEBUG=False` y `ALLOWED_HOSTS=127.0.0.1,localhost`:
  `python manage.py check --deploy` → solo queda el warning `security.W009`
  (el `SECRET_KEY` de ejemplo lleva el prefijo `django-insecure-`). Se
  resuelve poniendo un `SECRET_KEY` real en el `.env` del servidor; no se
  commitea.

## Qué falta

- **Deploy real en un servidor público**: aprovisionamiento del host, proxy
  inverso + certificado TLS, base de datos productiva, servidor WSGI
  (gunicorn/uWSGI), `collectstatic` y servido de estáticos, y generación del
  `SECRET_KEY` productivo. Queda para el próximo sprint.
- Revisar los endpoints de Keycloak/OIDC (hoy apuntan a `localhost:8080`)
  cuando exista el entorno de producción.
