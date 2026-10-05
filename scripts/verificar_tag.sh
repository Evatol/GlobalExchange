#!/usr/bin/env bash
# Verifica que el repositorio esté exactamente en el tag pedido para la
# revisión (SCC). Uso:
#
#   ./scripts/verificar_tag.sh v1.3.0
#
set -euo pipefail
TAG="${1:?Uso: $0 <tag>   (ej: v1.3.0)}"

echo "== Trayendo tags del remoto =="
# --force: si un tag se movió en el remoto, se actualiza también acá. Sin
# esto, una copia que ya tenía la versión anterior del tag rechaza la nueva
# ("sobrescribiría tag existente") y el script se corta en este paso.
git fetch --tags --force origin

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
# Mismo formato que "git log -1" pero sin la línea Date. La fecha sigue en
# el historial: se ve con "git log -1".
git log -1 --format='commit %H%d'
PADRES="$(git log -1 --format='%p')"
if [ "$(wc -w <<<"$PADRES")" -gt 1 ]; then
    echo "Merge: $PADRES"
fi
git log -1 --format='Author: %an <%ae>%n%n%w(0,4,4)%B'

echo
echo "OK: el repositorio está parado en el tag '$TAG'."
