#!/usr/bin/env bash
# Corre el chequeo del proyecto y toda la suite de pruebas unitarias (PUN).
# Uso:
#
#   ./scripts/pruebas.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== manage.py check =="
venv/bin/python manage.py check

echo
echo "== Pruebas unitarias (manage.py test) =="
venv/bin/python manage.py test --verbosity 2
