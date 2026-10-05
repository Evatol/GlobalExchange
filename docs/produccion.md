# Ambiente de producción (AMB - Hito 5)

El proyecto tiene dos ambientes con el **mismo código** y distinta
configuración. Cada uno se levanta con un solo comando.

| | Desarrollo | Producción |
|---|---|---|
| Comando | `./scripts/levantar_sistema.sh` | `./scripts/levantar_sistema.sh --prod` |
| Archivo | `docker-compose.yml` | `docker-compose.prod.yml` |
| Servidor | `runserver` (se recarga al editar) | **gunicorn**, 3 workers |
| `DEBUG` | `True` | `False` |
| Estáticos | los sirve Django | `collectstatic` + **WhiteNoise** |
| Código | montado desde el disco | dentro de la imagen: corre lo que se construyó |
| Base de datos | volumen `postgres_data` | volumen propio `postgres_prod_data` |
| Keycloak | volumen `keycloak_data` | volumen propio `keycloak_prod_data` |

## Qué se configuró

- **Configuración por variables de entorno** con `django-environ`
  (`config/settings.py`): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, base de
  datos y Keycloak. Si una variable falta, se usa el valor de desarrollo.
  `.env.example` documenta todas; el `.env` real no se versiona.
- **Servidor de aplicación:** gunicorn (`docker-compose.prod.yml`), en lugar
  del servidor de desarrollo de Django.
- **Archivos estáticos:** `docker-entrypoint.sh` corre `collectstatic` al
  arrancar cuando `DEBUG=False`, y WhiteNoise los sirve comprimidos y con
  caché (`CompressedManifestStaticFilesStorage`).
- **`SECRET_KEY` propia** de producción, distinta de la de desarrollo.
- **Endurecimiento de seguridad** cuando `DEBUG=False` (final de
  `settings.py`): redirección a HTTPS, cookies de sesión y CSRF seguras, HSTS
  y `SECURE_PROXY_SSL_HEADER` para operar detrás de un proxy que termina TLS.
  Cada una se puede desactivar por variable de entorno (ver limitaciones).
- **Cabeceras de seguridad** de Django: `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`,
  `Cross-Origin-Opener-Policy`.
- **Datos separados:** producción tiene sus propios volúmenes; lo que se hace
  en desarrollo no toca la base productiva.

## Cómo se verifica

```bash
./scripts/levantar_sistema.sh --prod
./scripts/verificar_produccion.sh
```

`verificar_produccion.sh` comprueba, con un resultado por línea:

1. que responde gunicorn y no el `runserver`;
2. que `DEBUG` está apagado y una URL inexistente no expone detalles internos;
3. que WhiteNoise sirve los estáticos;
4. las cabeceras de seguridad;
5. `manage.py check --deploy` (ver abajo);
6. que el código corre desde la imagen, sin nada montado desde el disco;
7. que Postgres usa el volumen de producción;
8. que el login redirige a Keycloak y Keycloak responde.

Si lo que está levantado es desarrollo, lo avisa en vez de dar resultados que
no corresponden.

`manage.py check --deploy` solo deja tres avisos, los tres por la misma
razón (no hay HTTPS, ver limitaciones): `security.W008`
(`SECURE_SSL_REDIRECT`), `security.W012` (`SESSION_COOKIE_SECURE`) y
`security.W016` (`CSRF_COOKIE_SECURE`).

## Limitaciones conocidas

- **Sin HTTPS.** No hay dominio ni certificado, así que
  `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE` están
  en `False` en `docker-compose.prod.yml`. Con un certificado (por ejemplo
  detrás de Nginx o Caddy) se pasan a `True` por variable de entorno, sin
  tocar código. HSTS ya está configurado, pero el navegador solo lo aplica
  sobre HTTPS.
- **Keycloak en modo `start-dev`.** Su modo de producción (`start`) exige
  HTTPS y un hostname público: misma limitación que el punto anterior.
- **Secretos con valor por defecto en el compose.** `SECRET_KEY`,
  `OIDC_RP_CLIENT_SECRET` y la contraseña de la base tienen un default en
  `docker-compose.prod.yml` para que el ambiente levante sin pasos manuales
  en la demo. Todos se pueden sobrescribir por variable de entorno; en un
  despliegue real se pasan desde fuera del repositorio.

## Qué falta para un servidor público

Es infraestructura, no código: un host, un dominio, un certificado TLS y un
proxy inverso. Con eso se activan las tres variables de HTTPS, Keycloak pasa a
`start` y los secretos se cargan desde el entorno del servidor.
