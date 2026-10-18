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


## Despliegue completo con un solo comando

\`\`\`bash
./scripts/levantar_sistema.sh --prod
\`\`\`

El script hace seis pasos y se puede correr cuantas veces haga falta, porque
cada uno es idempotente:

1. verifica que Docker esté instalado y corriendo;
2. revisa que los puertos 8080 y 8000 estén libres;
3. levanta el stack (`docker compose up --build -d`: si ya estaba levantado,
   solo recrea lo que cambió);
4. espera a que respondan Django **y** Keycloak;
5. carga los datos de demostración (`seed_datos_demo`, ver más abajo);
6. verifica facturación y terminales (`verificar_despliegue`).

Si el paso 4 o el 6 fallan, el script termina con código 1 y apunta a la
sección *Si la verificación falla*. Opciones útiles: `--limpio` (borra los
datos y arranca de cero), `--sin-datos` (no carga la demo y la verificación no
exige datos) y `--sin-verificar`.

Para reconstruir el sistema desde un tag en una carpeta limpia (control de
versiones, SCC):

\`\`\`bash
./scripts/arrancar_desde_cero.sh v1.5.0 /tmp/GlobalExchange-demo
\`\`\`

Clona, instala dependencias, migra, carga los datos de demostración y corre la
verificación funcional. Con un tag anterior a la ampliación del despliegue,
avisa que ese tag no incluye los comandos y sigue.

## Datos de demostración

`seed_datos_demo` es **idempotente**: correrlo de nuevo no duplica nada. Deja:

- monedas con cotización, métodos de pago, clientes y los medios de pago del
  cliente demo;
- la sucursal *Casa Central* con `cajero_demo` y su caja abierta;
- las **terminales de autoservicio** (hoy, *Terminal Autoservicio Centro*):
  cada una es una sucursal con su propio cajero técnico, su caja abierta y su
  **stock inicial** de billetes, repartido por denominación;
- operaciones exitosas de `cliente_demo` con su **factura emitida**.

Cómo evita duplicar: cada dato se busca antes de crearlo (por nombre,
documento o por una marca en la operación), y la caja se abre con su carga
inicial **solo la primera vez**. Una caja que el administrador cerró no se
vuelve a abrir ni a cargar: eso se hace a mano desde *Cajas*.

## Cómo se verifica

\`\`\`bash
./scripts/levantar_sistema.sh --prod
./scripts/verificar_produccion.sh
\`\`\`

`verificar_produccion.sh` comprueba, con un resultado por línea:

1. que responde gunicorn y no el `runserver`;
2. que `DEBUG` está apagado y una URL inexistente no expone detalles internos;
3. que WhiteNoise sirve los estáticos;
4. las cabeceras de seguridad;
5. `manage.py check --deploy` (ver abajo);
6. que el código corre desde la imagen, sin nada montado desde el disco;
7. que Postgres usa el volumen de producción;
8. que el login redirige a Keycloak y Keycloak responde;
9. **facturación y terminales**, con `manage.py verificar_despliegue` (corre
   dentro del contenedor, con un usuario temporal que no deja rastros): que la
   base responda, que el listado de facturas y las pantallas de caja
   funcionen, que haya facturas emitidas, que se genere el PDF de una de ellas
   y que cada terminal tenga su caja abierta con billetes.

Si lo que está levantado es desarrollo, lo avisa en vez de dar resultados que
no corresponden. Si algo falla, termina con código 1 y emite un **reporte de
fallo** con la lista de lo que falló. `verificar_despliegue --sin-datos` solo
comprueba que las pantallas respondan, para un ambiente sin datos de demo.

`manage.py check --deploy` solo deja tres avisos, los tres por la misma
razón (no hay HTTPS, ver limitaciones): `security.W008`
(`SECURE_SSL_REDIRECT`), `security.W012` (`SESSION_COOKIE_SECURE`) y
`security.W016` (`CSRF_COOKIE_SECURE`).

## Si la verificación falla

El reporte lista cada comprobación que falló. Este es el procedimiento para
cada una:

| Falla | Causa probable | Cómo resolverla |
|---|---|---|
| "El sistema no está levantado" | El contenedor `web` no corre | `./scripts/levantar_sistema.sh --prod`; si no arranca, `docker compose -f docker-compose.prod.yml logs web` |
| "Lo que está corriendo es el ambiente de DESARROLLO" | Desarrollo y producción usan los mismos nombres de contenedor | `docker compose down` y luego `./scripts/levantar_sistema.sh --prod` |
| No responde gunicorn / `DEBUG` encendido | Se levantó con otro compose o se pisó la variable `DEBUG` | Revisar `DEBUG` en `docker-compose.prod.yml` y reconstruir con `up --build` |
| Los estáticos no se sirven | No corrió `collectstatic` | Ver los logs de `web`; `docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput` |
| `check --deploy` con problemas inesperados | Una variable de seguridad cambió | Leer el aviso y corregir la variable; solo W008, W012 y W016 son aceptados |
| Postgres no usa el volumen de producción | Se mezclaron los ambientes | `docker compose down` y volver a levantar con `--prod` |
| El login no llega a Keycloak | Keycloak todavía arrancando, o `KC_HOSTNAME` mal | Esperar y repetir; `docker compose -f docker-compose.prod.yml logs keycloak` |
| **Base de datos**: no responde | Postgres no está sano o las credenciales `DB_*` no coinciden | `docker compose -f docker-compose.prod.yml ps` y revisar los logs de `postgres` |
| **Facturación, listado** o **Caja**: error o código distinto de 200 | Falta aplicar migraciones o hay un error en la pantalla | `docker compose -f docker-compose.prod.yml exec web python manage.py migrate` y mirar `logs web` |
| **Facturación, datos**: no hay facturas emitidas | No se cargó la demo | `docker compose -f docker-compose.prod.yml exec web python manage.py seed_datos_demo` |
| **Facturación, PDF**: no se generó | Falta `reportlab` en la imagen o hay un dato inconsistente | Reconstruir con `up --build` y revisar `requirements.txt` |
| **Terminal, stock**: sin caja abierta con billetes | No se cargó la demo, o el administrador cerró la caja | Correr `seed_datos_demo`; si la caja estaba cerrada, abrirla desde *Cajas* con su carga inicial |

Después de resolverlo, volver a correr `./scripts/verificar_produccion.sh`
hasta que termine en verde.

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
