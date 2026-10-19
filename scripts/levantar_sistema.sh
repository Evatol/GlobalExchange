#!/usr/bin/env bash
# Levanta TODO el sistema (Postgres + Keycloak + Django) con Docker, espera a
# que esté listo, carga los datos de demostración (terminales con su caja y
# stock, facturas de ejemplo) y verifica que facturación y terminales
# respondan. Se puede correr cuantas veces haga falta: no duplica datos. Al
# terminar imprime las URLs y los usuarios con los que entrar.
#
# Uso:
#
#   ./scripts/levantar_sistema.sh                 # desarrollo (runserver)
#   ./scripts/levantar_sistema.sh --prod          # produccion (gunicorn, DEBUG=False)
#   ./scripts/levantar_sistema.sh --limpio        # borra los datos y arranca de cero
#   ./scripts/levantar_sistema.sh --sin-datos     # no carga los datos de demo
#   ./scripts/levantar_sistema.sh --forzar        # sigue aunque haya puertos ocupados
#   ./scripts/levantar_sistema.sh --sin-verificar # no corre la verificacion final
#   ./scripts/levantar_sistema.sh --con-correo    # + verificacion por correo (necesita
#                                                 #   KEYCLOAK_SMTP_PASSWORD en tu .env)
#
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.yml"
AMBIENTE="desarrollo"
LIMPIO="no"
CARGAR_DATOS="si"
FORZAR="no"
VERIFICAR="si"
CON_CORREO="no"

for arg in "$@"; do
    case "$arg" in
        --prod)      COMPOSE_FILE="docker-compose.prod.yml"; AMBIENTE="produccion" ;;
        --limpio)    LIMPIO="si" ;;
        --sin-datos) CARGAR_DATOS="no" ;;
        --forzar)     FORZAR="si" ;;
        --sin-verificar) VERIFICAR="no" ;;
        --con-correo) CON_CORREO="si" ;;
        -h|--help)   sed -n '2,17p' "$0"; exit 0 ;;
        *)           echo "Opcion desconocida: $arg (usa --help)"; exit 1 ;;
    esac
done

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "== 1/6 Verificando Docker =="
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker no esta instalado." >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: el demonio de Docker no esta corriendo (arranca Docker Desktop)." >&2
    exit 1
fi
echo "   Docker OK."

echo
echo "== 2/6 Revisando puertos (8080, 8000) =="
# El 5432 no se revisa: el stack no publica Postgres al host justamente para
# poder convivir con el PostgreSQL local. Si los ocupa el propio stack no hay
# problema: docker compose los reutiliza.
EN_USO=""
for puerto in 8080 8000; do
    if ss -tln 2>/dev/null | grep -q ":${puerto}\b"; then
        EN_USO="${EN_USO} ${puerto}"
    fi
done
if [ -n "$EN_USO" ] && [ -z "$(compose ps -q 2>/dev/null)" ]; then
    echo "   PROBLEMA: estos puertos ya estan ocupados:${EN_USO}"
    echo
    echo "   Es tu entorno local de siempre. Paralo con:"
    echo
    echo "       docker stop keycloak-dev"
    echo "       pkill -f 'manage.py runserver'"
    echo
    echo "   ...y volve a correr este script."
    if [ "$FORZAR" = "si" ]; then
        echo "   (--forzar: sigo igual, puede fallar al levantar)"
    else
        exit 1
    fi
else
    echo "   Sin conflictos."
fi

if [ "$LIMPIO" = "si" ]; then
    echo
    echo "== Borrando datos previos (--limpio) =="
    compose down -v
fi

echo
echo "== 3/6 Levantando el stack ($AMBIENTE) =="
# Es idempotente: si ya esta levantado, compose solo recrea lo que cambio.
compose up --build -d

echo
echo "== 4/6 Esperando a que el sistema responda (Django y Keycloak) =="
printf "   "
for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "http://localhost:8000/api/divisas/" 2>/dev/null \
        && curl -fsS -o /dev/null "http://localhost:8080/realms/master" 2>/dev/null; then
        echo " listo."
        LISTO="si"
        break
    fi
    printf "."
    sleep 3
done
if [ "${LISTO:-no}" != "si" ]; then
    echo
    echo "ERROR: el sistema no respondio a tiempo (Django en 8000 y Keycloak en 8080)." >&2
    echo "Mira los logs con:" >&2
    echo "    docker compose -f $COMPOSE_FILE logs web keycloak" >&2
    echo "Como resolverlo: docs/produccion.md, seccion 'Si la verificacion falla'." >&2
    exit 1
fi

echo
echo "== 5/6 Datos de demostracion =="
if [ "$CARGAR_DATOS" = "si" ]; then
    # Idempotente: crea las terminales con su caja abierta y su stock inicial,
    # y las facturas de ejemplo, solo la primera vez.
    compose exec -T web python manage.py seed_datos_demo
else
    echo "   Omitidos (--sin-datos)."
fi

echo
echo "== 6/6 Verificando facturacion y terminales =="
if [ "$VERIFICAR" = "si" ]; then
    ARGS_VERIFICACION=""
    [ "$CARGAR_DATOS" = "si" ] || ARGS_VERIFICACION="--sin-datos"
    if ! compose exec -T web python manage.py verificar_despliegue $ARGS_VERIFICACION; then
        echo >&2
        echo "ERROR: la verificacion detecto fallas (las lineas FALLA de arriba)." >&2
        echo "El sistema quedo levantado, pero no completamente operativo." >&2
        echo "Como resolverlo: docs/produccion.md, seccion 'Si la verificacion falla'." >&2
        exit 1
    fi
else
    echo "   Omitida (--sin-verificar)."
fi

if [ "$CON_CORREO" = "si" ]; then
    echo
    echo "== Extra: verificacion por correo =="
    # El password sale del .env (que git ignora), nunca del repo.
    if [ -z "${KEYCLOAK_SMTP_PASSWORD:-}" ] && [ -f .env ]; then
        KEYCLOAK_SMTP_PASSWORD="$(grep -E '^KEYCLOAK_SMTP_PASSWORD=' .env | cut -d= -f2- | tr -d '"'"'"' ' || true)"
    fi
    if [ -z "${KEYCLOAK_SMTP_PASSWORD:-}" ]; then
        echo "   No encontre KEYCLOAK_SMTP_PASSWORD."
        echo "   Agregala a tu archivo .env (no se sube a git):"
        echo "       KEYCLOAK_SMTP_PASSWORD=xxxxxxxxxxxxxxxx"
        echo "   El sistema queda levantado igual, pero sin verificacion por correo."
    else
        KEYCLOAK_SMTP_PASSWORD="$KEYCLOAK_SMTP_PASSWORD" \
            compose exec -T web python manage.py configure_keycloak_registration
    fi
fi

cat <<'FIN'

========================================================================
 SISTEMA LISTO
========================================================================

  Aplicacion .... http://localhost:8000/
  Keycloak ...... http://localhost:8080/   (admin / admin)
  Facturas ...... http://localhost:8000/api/facturacion/gestion/facturas/

  Usuarios (misma contrasena para todos: Demo1234!)

    admin_demo      administrador   ve y administra todo
    analista_demo   analista        monedas y cotizaciones, sin roles
    cliente_demo    usuario final   opera sobre "Comercial Uno" y ve sus facturas
    cajero_demo     cajero          atiende en el mostrador (Caja #1, solo el modulo de caja)
    angel           (sin rol)       para asignarle un rol en la demo

  Terminal de autoservicio: "Terminal Autoservicio Centro", con su caja
  abierta y billetes (la administra admin_demo desde Terminales, boton Abrir).
  Ahi cliente_demo se identifica y opera en efectivo.

  Para volver a verificar:  ./scripts/verificar_produccion.sh   (con --prod)
  Para apagar:   docker compose down
  Ver los logs:  docker compose logs -f web

========================================================================
FIN