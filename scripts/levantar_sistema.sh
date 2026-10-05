#!/usr/bin/env bash
# Levanta TODO el sistema (Postgres + Keycloak + Django) con Docker, espera a
# que esté listo y carga los datos de demostración. Al terminar imprime las
# URLs y los usuarios con los que entrar.
#
# Uso:
#
#   ./scripts/levantar_sistema.sh                 # desarrollo (runserver)
#   ./scripts/levantar_sistema.sh --prod          # produccion (gunicorn, DEBUG=False)
#   ./scripts/levantar_sistema.sh --limpio        # borra los datos y arranca de cero
#   ./scripts/levantar_sistema.sh --sin-datos     # no carga los datos de demo
#   ./scripts/levantar_sistema.sh --forzar        # sigue aunque haya puertos ocupados
#   ./scripts/levantar_sistema.sh --con-correo    # + verificacion por correo (necesita
#                                                 #   KEYCLOAK_SMTP_PASSWORD en tu .env)
#   ./scripts/levantar_sistema.sh --presentacion  # pasa a develop actualizado, muestra lo
#                                                 #   hecho desde v1.4.0 y levanta --limpio
#
set -euo pipefail
# Ruta absoluta del script, para poder volver a ejecutarlo (--presentacion)
# aunque se lo haya llamado desde otra carpeta.
ESTE_SCRIPT="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.yml"
AMBIENTE="desarrollo"
LIMPIO="no"
CARGAR_DATOS="si"
FORZAR="no"
CON_CORREO="no"
PRESENTACION="no"
TAG_ENTREGA="v1.4.0"         # la entrega del Sprint 3; se presenta lo hecho después
RAMA_PRESENTACION="develop"  # rama desde la que se presenta (autorizado por la cátedra)

for arg in "$@"; do
    case "$arg" in
        --prod)      COMPOSE_FILE="docker-compose.prod.yml"; AMBIENTE="produccion" ;;
        --limpio)    LIMPIO="si" ;;
        --sin-datos) CARGAR_DATOS="no" ;;
        --forzar)     FORZAR="si" ;;
        --con-correo) CON_CORREO="si" ;;
        --presentacion) PRESENTACION="si" ;;
        -h|--help)   sed -n '2,16p' "$0"; exit 0 ;;
        *)           echo "Opcion desconocida: $arg (usa --help)"; exit 1 ;;
    esac
done

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

if [ "$PRESENTACION" = "si" ]; then
    # Muestra cada comando antes de correrlo, para que se vea en pantalla.
    paso() { echo "\$ $*"; "$@"; }

    echo "== Presentacion: pasar a $RAMA_PRESENTACION actualizado =="
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "ERROR: hay cambios sin commitear en archivos del repositorio." >&2
        echo "Commitealos o descartalos antes de cambiar de rama:" >&2
        git status --short --untracked-files=no >&2
        exit 1
    fi
    git fetch --quiet --tags --force origin
    paso git checkout "$RAMA_PRESENTACION"
    # --ff-only: si la rama local se hubiera separado del remoto, falla en
    # vez de crear un merge en medio de la presentacion.
    paso git pull --ff-only origin "$RAMA_PRESENTACION"
    echo
    echo "== Lo hecho despues de la entrega ($TAG_ENTREGA) =="
    paso git log --oneline "$TAG_ENTREGA..$RAMA_PRESENTACION"
    if [ -z "$(git log --oneline "$TAG_ENTREGA..$RAMA_PRESENTACION")" ]; then
        echo "   ($RAMA_PRESENTACION no tiene nada nuevo respecto de $TAG_ENTREGA)"
    fi
    echo

    # Se vuelve a ejecutar el script ya actualizado por el pull, en limpio.
    # Se pasan las demas opciones (por ejemplo --forzar) tal cual.
    OTRAS=()
    for arg in "$@"; do
        [ "$arg" != "--presentacion" ] && [ "$arg" != "--limpio" ] && OTRAS+=("$arg")
    done
    exec "$ESTE_SCRIPT" --limpio ${OTRAS[@]+"${OTRAS[@]}"}
fi

echo "== 1/5 Verificando Docker =="
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
echo "== 2/5 Revisando puertos (8080, 8000) =="
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
echo "== 3/5 Levantando el stack ($AMBIENTE) =="
compose up --build -d

echo
echo "== 4/5 Esperando a que el sistema responda =="
printf "   "
for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "http://localhost:8000/api/divisas/" 2>/dev/null; then
        echo " listo."
        LISTO="si"
        break
    fi
    printf "."
    sleep 3
done
if [ "${LISTO:-no}" != "si" ]; then
    echo
    echo "ERROR: el sistema no respondio a tiempo. Mira los logs con:" >&2
    echo "    docker compose -f $COMPOSE_FILE logs web" >&2
    exit 1
fi

echo
echo "== 5/5 Datos de demostracion =="
if [ "$CARGAR_DATOS" = "si" ]; then
    compose exec -T web python manage.py seed_datos_demo
else
    echo "   Omitidos (--sin-datos)."
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

  Usuarios (misma contrasena para todos: Demo1234!)

    admin_demo      administrador   ve y administra todo
    analista_demo   analista        monedas y cotizaciones, sin roles
    cliente_demo    usuario final   opera sobre "Comercial Uno"
    angel           (sin rol)       para asignarle un rol en la demo

  Para apagar:   docker compose down
  Ver los logs:  docker compose logs -f web

========================================================================
FIN
