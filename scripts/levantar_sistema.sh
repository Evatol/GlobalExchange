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
#
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.yml"
AMBIENTE="desarrollo"
LIMPIO="no"
CARGAR_DATOS="si"
FORZAR="no"

for arg in "$@"; do
    case "$arg" in
        --prod)      COMPOSE_FILE="docker-compose.prod.yml"; AMBIENTE="produccion" ;;
        --limpio)    LIMPIO="si" ;;
        --sin-datos) CARGAR_DATOS="no" ;;
        --forzar)    FORZAR="si" ;;
        -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
        *)           echo "Opcion desconocida: $arg (usa --help)"; exit 1 ;;
    esac
done

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

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
echo "== 2/5 Revisando puertos (5432, 8080, 8000) =="
# Si los ocupa el propio stack no hay problema: docker compose los reutiliza.
EN_USO=""
for puerto in 5432 8080 8000; do
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
    echo "       sudo systemctl stop postgresql"
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

cat <<'FIN'

========================================================================
 SISTEMA LISTO
========================================================================

  Aplicacion .... http://localhost:8000/
  Keycloak ...... http://localhost:8080/   (admin / admin)

  Usuarios (misma contrasena para los tres: Demo1234!)

    admin_demo      administrador   ve y administra todo
    analista_demo   analista        monedas y cotizaciones, sin roles
    cliente_demo    usuario final   opera sobre "Comercial Uno"

  Para apagar:   docker compose down
  Ver los logs:  docker compose logs -f web

========================================================================
FIN
