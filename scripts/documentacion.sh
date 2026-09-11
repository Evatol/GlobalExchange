#!/usr/bin/env bash
# Instala las dependencias de documentación y compila Sphinx (PDO).
# Falla si aparece algún warning nuevo (-W), igual que en el CI.
# Uso:
#
#   ./scripts/documentacion.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Instalando requirements-dev.txt =="
venv/bin/pip install -q -r requirements-dev.txt

echo
echo "== Compilando documentación (falla si hay warnings) =="
venv/bin/sphinx-build -b html -W --keep-going docs docs/_build/html

echo
echo "OK: documentación generada en docs/_build/html/index.html"
