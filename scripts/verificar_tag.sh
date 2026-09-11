#!/usr/bin/env bash
# Verifica que el repositorio esté exactamente en el tag pedido para la
# revisión (SCC). Uso:
#
#   ./scripts/verificar_tag.sh v1.3.0
#
set -euo pipefail
TAG="${1:?Uso: $0 <tag>   (ej: v1.3.0)}"

echo "== Trayendo tags del remoto =="
git fetch --tags origin

echo
echo "== Tags disponibles en el repositorio =="
git tag -l

echo
echo "== Haciendo checkout de '$TAG' =="
git checkout "$TAG"

echo
echo "== Confirmando que HEAD es EXACTAMENTE '$TAG' (falla si no lo es) =="
git describe --tags --exact-match

echo
echo "== Commit en ese punto =="
git log -1

echo
echo "OK: el repositorio está parado en el tag '$TAG'."
