#!/usr/bin/env bash
# Verifica que el ambiente de PRODUCCIÓN (AMB) esté montado y funcionando,
# y muestra un resultado por cada punto. Pensado para la revisión: no hay que
# tipear ningún curl de memoria.
#
# Uso:
#
#   ./scripts/levantar_sistema.sh --prod     # primero, levantar producción
#   ./scripts/verificar_produccion.sh
#
# Qué verifica:
#
#   1. El servidor es gunicorn, no el runserver de desarrollo.
#   2. DEBUG está apagado (y una URL inexistente no expone detalles internos).
#   3. Los estáticos los sirve WhiteNoise.
#   4. Cabeceras de seguridad presentes.
#   5. manage.py check --deploy: solo quedan los avisos de HTTPS (documentados).
#   6. El código corre desde la imagen, no montado desde el disco.
#   7. La base de datos es la de producción (volumen propio).
#   8. El login redirige a Keycloak y Keycloak responde.
#
# Termina con código 0 si todo pasó, 1 si algo falló.
#
set -uo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

URL="http://localhost:8000"
PROD="docker-compose.prod.yml"
prod() { docker compose -f "$PROD" "$@"; }

PASARON=0
FALLARON=0
ok()    { printf "   ✅ %s\n" "$1"; PASARON=$((PASARON + 1)); }
falla() { printf "   ❌ %s\n" "$1"; FALLARON=$((FALLARON + 1)); }
info()  { printf "      %s\n" "$1"; }
titulo() { printf "\n%s\n" "$1"; }

echo "========================================================================"
echo " Verificación del ambiente de PRODUCCIÓN (AMB)"
echo "========================================================================"

# Desarrollo y producción usan los mismos nombres de contenedor: hay que
# mirar QUÉ está corriendo, no solo si hay algo corriendo.
WEB_ID="$(prod ps -q web 2>/dev/null)"
if [ -z "$WEB_ID" ]; then
    echo
    echo "El sistema no está levantado. Primero corré:"
    echo "    ./scripts/levantar_sistema.sh --prod"
    exit 1
fi
COMANDO="$(docker inspect -f '{{join .Config.Cmd " "}}' "$WEB_ID" 2>/dev/null)"
if [[ "$COMANDO" != *gunicorn* ]]; then
    echo
    echo "Lo que está corriendo es el ambiente de DESARROLLO ($COMANDO)."
    echo "Para verificar producción, primero levantala:"
    echo "    ./scripts/levantar_sistema.sh --prod"
    exit 1
fi

# ----------------------------------------------------------------------
titulo "1. Servidor de aplicación"
SERVER="$(curl -sI "$URL/api/divisas/" | tr -d '\r' | grep -i '^server:' | cut -d' ' -f2-)"
WORKERS="$(echo "$COMANDO" | grep -oE -- '--workers [0-9]+' | awk '{print $2}')"
if [ "$SERVER" = "gunicorn" ]; then
    ok "Responde gunicorn (${WORKERS:-?} workers), no el runserver de desarrollo"
else
    falla "Se esperaba 'Server: gunicorn' y vino '${SERVER:-nada}'"
fi

# ----------------------------------------------------------------------
titulo "2. DEBUG apagado"
DEBUG_VALOR="$(prod exec -T web python manage.py shell --no-imports \
    -c 'from django.conf import settings; print(settings.DEBUG)' 2>/dev/null | tail -1)"
if [ "$DEBUG_VALOR" = "False" ]; then
    ok "settings.DEBUG = False"
else
    falla "settings.DEBUG = ${DEBUG_VALOR:-?} (debería ser False)"
fi
PAGINA_404="$(curl -s "$URL/esta-url-no-existe/")"
CODIGO_404="$(curl -s -o /dev/null -w '%{http_code}' "$URL/esta-url-no-existe/")"
if [ "$CODIGO_404" = "404" ] && ! grep -qiE 'URLconf|Traceback|settings\.py' <<<"$PAGINA_404"; then
    ok "Una URL inexistente da 404 sin mostrar detalles internos"
else
    falla "La página 404 expone detalles internos (o no devolvió 404: $CODIGO_404)"
fi

# ----------------------------------------------------------------------
titulo "3. Archivos estáticos"
ESTATICO="$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$URL/static/admin/css/base.css")"
CACHE="$(curl -sI "$URL/static/admin/css/base.css" | tr -d '\r' | grep -i '^cache-control:' | cut -d' ' -f2-)"
if [[ "$ESTATICO" == 200\ text/css* ]]; then
    ok "WhiteNoise sirve los estáticos (base.css -> 200, ${CACHE:-sin cache-control})"
else
    falla "No se sirvió base.css correctamente ($ESTATICO)"
fi

# ----------------------------------------------------------------------
titulo "4. Cabeceras de seguridad"
CABECERAS="$(curl -sI "$URL/api/divisas/" | tr -d '\r')"
for cabecera in "X-Frame-Options: DENY" "X-Content-Type-Options: nosniff" "Referrer-Policy: same-origin"; do
    if grep -qi "^$cabecera" <<<"$CABECERAS"; then
        ok "$cabecera"
    else
        falla "Falta la cabecera '$cabecera'"
    fi
done

# ----------------------------------------------------------------------
titulo "5. Chequeo de producción de Django (manage.py check --deploy)"
DEPLOY="$(prod exec -T web python manage.py check --deploy 2>&1)"
AVISOS="$(grep -oE 'security\.W[0-9]+' <<<"$DEPLOY" | sort -u | tr '\n' ' ')"
# Los únicos aceptados: los tres que dependen de tener HTTPS (ver la nota al
# principio de docker-compose.prod.yml).
INESPERADOS="$(grep -oE '\((security|[a-z_]+)\.[EW][0-9]+\)' <<<"$DEPLOY" \
    | grep -vE 'security\.W(008|012|016)' | sort -u | tr '\n' ' ')"
if [ -z "$INESPERADOS" ]; then
    ok "Sin problemas, salvo los avisos de HTTPS esperados: ${AVISOS:-ninguno}"
    info "W008/W012/W016 = sin HTTPS (no hay dominio ni certificado)."
    info "Con un certificado se activan por variable de entorno, sin tocar código."
else
    falla "check --deploy encontró problemas inesperados: $INESPERADOS"
fi

# ----------------------------------------------------------------------
titulo "6. El código corre desde la imagen"
MONTAJES="$(docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}} {{end}}{{end}}' "$WEB_ID")"
if [ -z "$MONTAJES" ]; then
    ok "No hay código montado desde el disco: corre lo que se construyó en la imagen"
else
    falla "Hay código montado desde el disco: $MONTAJES"
fi

# ----------------------------------------------------------------------
titulo "7. Base de datos propia de producción"
PG_ID="$(prod ps -q postgres 2>/dev/null)"
VOLUMEN="$(docker inspect -f '{{range .Mounts}}{{.Name}} {{end}}' "$PG_ID" 2>/dev/null)"
if [[ "$VOLUMEN" == *postgres_prod_data* ]]; then
    ok "Postgres usa el volumen de producción ($(echo $VOLUMEN | tr -d ' ')), separado del de desarrollo"
else
    falla "Postgres no usa el volumen de producción (usa: ${VOLUMEN:-?})"
fi

# ----------------------------------------------------------------------
titulo "8. Login con Keycloak"
REDIRECCION="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$URL/api/usuarios/")"
LOGIN="$(curl -sL -o /dev/null -w '%{http_code} %{url_effective}' "$URL/oidc/authenticate/")"
if [[ "$REDIRECCION" == 302* ]] && [[ "$LOGIN" == 200\ http://localhost:8080/* ]]; then
    ok "Sin sesión redirige al login, y Keycloak muestra su pantalla de inicio de sesión"
else
    falla "El login no llega a Keycloak (menú: $REDIRECCION / login: $LOGIN)"
fi

# ----------------------------------------------------------------------
echo
echo "========================================================================"
if [ "$FALLARON" -eq 0 ]; then
    echo " ✅ AMBIENTE DE PRODUCCIÓN OK: $PASARON verificaciones pasaron"
else
    echo " ❌ $FALLARON verificaciones fallaron ($PASARON pasaron)"
fi
echo "========================================================================"
[ "$FALLARON" -eq 0 ]
