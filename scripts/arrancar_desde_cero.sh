#!/usr/bin/env bash
# Clona el repositorio en una carpeta nueva, hace checkout del tag pedido,
# crea un entorno virtual limpio, instala las dependencias, migra la base de
# datos y, si el tag las incluye, carga los datos de demostración (terminales
# con su caja y stock, facturas de ejemplo) y verifica facturación y
# terminales. Demuestra que el sistema se reconstruye enteramente desde el
# control de versiones (SCC), sin pasos manuales ocultos.
#
# Usa la MISMA base de datos Postgres de siempre (mismas credenciales por
# defecto de config/settings.py): no borra ni reemplaza los datos de demo
# ya cargados. "migrate" solo confirma que el esquema ya está al día y los
# datos de demostración se cargan de forma idempotente: correrlo de nuevo no
# duplica nada.
#
# Uso:
#
#   ./scripts/arrancar_desde_cero.sh v1.3.0 /tmp/GlobalExchange-demo
#
set -euo pipefail
TAG="${1:?Uso: $0 <tag> <carpeta_destino>}"
DEST="${2:?Uso: $0 <tag> <carpeta_destino>}"
REPO_URL="https://github.com/Evatol/GlobalExchange.git"

echo "== Clonando un repositorio limpio en $DEST =="
rm -rf "$DEST"
git clone "$REPO_URL" "$DEST"
cd "$DEST"

echo
echo "== Checkout de '$TAG' =="
git checkout "$TAG"
git describe --tags --exact-match

echo
echo "== Creando entorno virtual e instalando dependencias =="
python -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

echo
echo "== Migrando la base de datos =="
venv/bin/python manage.py migrate

# Los tags anteriores a la ampliación del despliegue no traen estos comandos:
# en ese caso se avisa y se sigue, para que el script sirva con cualquier tag.
comando_disponible() {
    venv/bin/python manage.py help --commands | grep -qx "$1"
}

echo
echo "== Datos de demostracion: terminales, cajas con stock y facturas (idempotente) =="
if comando_disponible seed_datos_demo; then
    venv/bin/python manage.py seed_datos_demo
else
    echo "   Este tag no incluye seed_datos_demo: se omite."
fi

echo
echo "== Verificando facturacion y terminales =="
if comando_disponible verificar_despliegue; then
    if ! venv/bin/python manage.py verificar_despliegue; then
        echo "ERROR: la verificacion detecto fallas (las lineas FALLA de arriba)." >&2
        echo "Como resolverlo: docs/produccion.md, seccion 'Si la verificacion falla'." >&2
        exit 1
    fi
else
    echo "   Este tag no incluye verificar_despliegue: se omite."
fi

echo
echo "OK. Para levantar el servidor desde esta copia limpia:"
echo "  cd $DEST && venv/bin/python manage.py runserver 127.0.0.1:8000"