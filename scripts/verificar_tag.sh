#!/usr/bin/env bash
# Verifica que el repositorio esté exactamente en el tag pedido para la
# revisión (SCC) y después vuelve a develop, donde están las mejoras
# posteriores a la entrega (autorizado por la cátedra). Uso:
#
#   ./scripts/verificar_tag.sh v1.4.0              # muestra el tag y vuelve a develop
#   ./scripts/verificar_tag.sh v1.4.0 --quedarse   # deja la carpeta parada en el tag
#
# Después, para levantar el sistema:  ./scripts/levantar_sistema.sh --limpio
#
set -euo pipefail
TAG="${1:?Uso: $0 <tag> [--quedarse]   (ej: v1.4.0)}"
QUEDARSE="no"
[ "${2:-}" = "--quedarse" ] && QUEDARSE="si"
RAMA_PRESENTACION="develop"

# Muestra cada comando antes de correrlo, para que se vea en pantalla.
paso() { echo "\$ $*"; "$@"; }

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "ERROR: hay cambios sin commitear en archivos del repositorio." >&2
    echo "Commitealos o descartalos antes de cambiar de versión:" >&2
    git status --short --untracked-files=no >&2
    exit 1
fi

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

if [ "$QUEDARSE" = "si" ]; then
    exit 0
fi

echo
echo "== Volviendo a $RAMA_PRESENTACION, con las mejoras posteriores a '$TAG' =="
paso git checkout --quiet "$RAMA_PRESENTACION"
# --ff-only: si la rama local se hubiera separado del remoto, falla en vez
# de crear un merge en medio de la presentación.
paso git pull --ff-only origin "$RAMA_PRESENTACION"

echo
echo "== Lo hecho después de la entrega ('$TAG') =="
paso git log --oneline "$TAG..$RAMA_PRESENTACION"

echo
echo "Siguiente paso:  ./scripts/levantar_sistema.sh --limpio"
