#!/bin/sh
# Arranque del contenedor de Django: espera a que Postgres y Keycloak estén
# arriba, migra, deja el realm de Keycloak listo para usar (idempotente) y
# recién ahí levanta el servidor. Pensado para "docker compose up" sin pasos
# manuales adicionales.
set -e

wait_for() {
    host="$1"
    port="$2"
    name="$3"
    echo "Esperando a $name ($host:$port)..."
    i=0
    while [ "$i" -lt 60 ]; do
        if python -c "import socket; socket.create_connection(('$host', $port), timeout=2)" 2>/dev/null; then
            echo "$name listo."
            return 0
        fi
        i=$((i + 1))
        sleep 2
    done
    echo "$name no respondio a tiempo ($host:$port)." >&2
    exit 1
}

wait_for "${DB_HOST:-postgres}" "${DB_PORT:-5432}" "Postgres"
wait_for "${KEYCLOAK_HOST:-keycloak}" "${KEYCLOAK_PORT:-8080}" "Keycloak"

python manage.py migrate --noinput

# Deja el realm de Keycloak configurado (roles, mapper de roles, idioma,
# direct access grants, post-logout redirect). Todos idempotentes: correrlos
# de nuevo en cada arranque no rompe nada. No incluye autoregistro/SMTP
# (configure_keycloak_registration): eso necesita una contraseña de
# aplicacion de Gmail real y se deja como paso manual y opcional.
if [ "${SKIP_KEYCLOAK_BOOTSTRAP:-false}" != "true" ]; then
    python manage.py configure_keycloak_realm
    python manage.py configure_keycloak_roles_negocio
    python manage.py configure_keycloak_roles
    python manage.py configure_keycloak_locale
    python manage.py configure_keycloak_direct_grants
    python manage.py configure_keycloak_logout

    if [ "${SEED_DEMO_USERS:-true}" = "true" ]; then
        python manage.py seed_usuarios_demo
    fi
fi

exec "$@"
