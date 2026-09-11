#!/usr/bin/env bash
# Clona el repositorio en una carpeta nueva, hace checkout del tag pedido,
# crea un entorno virtual limpio, instala las dependencias y migra la base
# de datos. Demuestra que el sistema se reconstruye enteramente desde el
# control de versiones (SCC), sin pasos manuales ocultos.
#
# Usa la MISMA base de datos Postgres de siempre (mismas credenciales por
# defecto de config/settings.py): no borra ni reemplaza los datos de demo
# ya cargados, "migrate" solo confirma que el esquema ya está al día.
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

echo
echo "OK. Para levantar el servidor desde esta copia limpia:"
echo "  cd $DEST && venv/bin/python manage.py runserver 127.0.0.1:8000"
