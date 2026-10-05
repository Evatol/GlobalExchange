#!/usr/bin/env bash
# Demostración de E4-28: cancelación de una transacción cuando la cotización
# cambia antes del pago.
#
# Hace falta porque, en esta versión, la pantalla de Comprar/Vender confirma
# la operación en el mismo momento en que se crea: todavía no existe el paso
# de pago (alcance del Sprint 4), así que no hay forma de que la cotización
# cambie "en el medio" desde el navegador. Este script simula ese paso:
#
#   ./scripts/demo_cancelacion.sh crear     # el cliente inicia una compra (queda PENDIENTE)
#   ./scripts/demo_cancelacion.sh estado    # cotización vigente y transacciones pendientes
#   ./scripts/demo_cancelacion.sh pagar     # el cliente paga: se confirma o se cancela
#
# Flujo de la demo:
#
#   1. ./scripts/demo_cancelacion.sh crear
#   2. En el navegador, como analista_demo: CRUD Cotizaciones -> USD -> Editar
#      y cambiar la tasa (por ejemplo 7350 / 7450).
#   3. ./scripts/demo_cancelacion.sh pagar        -> CANCELADA
#   4. Como cliente_demo: Historial -> aparece como "Cancelada".
#
# Si en el paso 2 no se cambia la cotización, el paso 3 la confirma (EXITOSA).
#
# Opciones de "crear":  --cantidad N   (por defecto 10)
#                       --moneda COD   (por defecto USD)
#                       --tipo COMPRA|VENTA (por defecto COMPRA)
#                       --usuario U    (por defecto cliente_demo)
# Opción de "pagar":    --id N   (por defecto, la pendiente más reciente)
#
set -euo pipefail
cd "$(dirname "$0")/.."

ACCION="${1:-}"
[ $# -gt 0 ] && shift

CANTIDAD="10"
MONEDA="USD"
TIPO="COMPRA"
USUARIO="cliente_demo"
TX_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --cantidad) CANTIDAD="$2"; shift 2 ;;
        --moneda)   MONEDA="$2"; shift 2 ;;
        --tipo)     TIPO="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
        --usuario)  USUARIO="$2"; shift 2 ;;
        --id)       TX_ID="$2"; shift 2 ;;
        *) echo "Opción desconocida: $1 (usá --help)"; exit 1 ;;
    esac
done

ayuda() { sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; }

case "$ACCION" in
    crear|estado|pagar) ;;
    -h|--help|"") ayuda; exit 0 ;;
    *) echo "Acción desconocida: $ACCION (usá crear, estado o pagar)"; exit 1 ;;
esac

if [ -z "$(docker compose ps -q web 2>/dev/null)" ]; then
    echo "El sistema no está levantado. Corré primero: ./scripts/levantar_sistema.sh" >&2
    exit 1
fi

# Los valores viajan como variables de entorno al contenedor, no pegados
# dentro del código Python.
django_shell() {
    docker compose exec -T \
        -e DEMO_CANTIDAD="$CANTIDAD" -e DEMO_MONEDA="$MONEDA" -e DEMO_TIPO="$TIPO" \
        -e DEMO_USUARIO="$USUARIO" -e DEMO_TX_ID="$TX_ID" \
        web python manage.py shell --no-imports
}

case "$ACCION" in
crear)
    django_shell <<'PY'
import os, sys
from decimal import Decimal, InvalidOperation
from apps.divisas.models import TasaCambio
from apps.transacciones.models import MedioPagoCliente, Transaccion
from apps.usuarios.models import Usuario

moneda, tipo = os.environ["DEMO_MONEDA"].upper(), os.environ["DEMO_TIPO"]
if tipo not in ("COMPRA", "VENTA"):
    sys.exit("El tipo debe ser COMPRA o VENTA.")
try:
    cantidad = Decimal(os.environ["DEMO_CANTIDAD"])
    assert cantidad > 0
except (InvalidOperation, AssertionError):
    sys.exit("La cantidad debe ser un número mayor a 0.")

usuario = Usuario.objects.filter(username=os.environ["DEMO_USUARIO"]).first()
if usuario is None:
    sys.exit(f"No existe el usuario {os.environ['DEMO_USUARIO']}.")
cliente = usuario.clientes.order_by("nombre").first()
if cliente is None:
    sys.exit(f"{usuario.username} no tiene ningún cliente asociado.")
medio = MedioPagoCliente.objects.filter(cliente=cliente, estado=True).first()
if medio is None:
    sys.exit(f"El cliente {cliente.nombre} no tiene medios de pago activos.")
tasa = TasaCambio.objects.activa_para(moneda)
if tasa is None:
    sys.exit(f"No hay cotización vigente para {moneda}.")

# Misma tasa que aplica la pantalla de Comprar/Vender.
tasa_aplicada = tasa.tasa_para(tipo)
tx = Transaccion(
    usuario=usuario, cliente=cliente, moneda=tasa.moneda,
    metodo_pago=medio.metodo_pago, tipo=tipo, cantidad=cantidad,
    tasa_cambio=tasa_aplicada, modalidad="DIGITAL",
)
tx.calcular_tasas_y_comisiones()
error = tx.validar_limite_cliente()
if error:
    sys.exit(error)
tx.save()  # queda PENDIENTE: todavía no se pagó

print()
print(f"  Transacción #{tx.id} creada  ->  {tx.estado}")
print(f"  Cliente ........ {cliente.nombre}")
print(f"  Operación ...... {tx.get_tipo_display()} de {tx.cantidad} {moneda}")
print(f"  Tasa guardada .. {tx.tasa_cambio}")
print(f"  Total .......... {tx.monto_total}")
print()
print("  Ahora cambiá la cotización de", moneda, "desde CRUD Cotizaciones")
print("  y después corré:  ./scripts/demo_cancelacion.sh pagar")
print()
PY
    ;;

estado)
    django_shell <<'PY'
import os
from apps.divisas.models import TasaCambio
from apps.transacciones.models import Transaccion

moneda = os.environ["DEMO_MONEDA"].upper()
tasa = TasaCambio.objects.activa_para(moneda)
print()
if tasa:
    print(f"  Cotización vigente de {moneda}: compra {tasa.tasa_compra} / venta {tasa.tasa_venta}")
else:
    print(f"  No hay cotización vigente de {moneda}.")
pendientes = Transaccion.objects.filter(estado="PENDIENTE").order_by("id")
print()
if not pendientes:
    print("  No hay transacciones pendientes de pago.")
for tx in pendientes:
    print(f"  #{tx.id}  {tx.get_tipo_display()} de {tx.cantidad} {tx.moneda.codigo}"
          f"  -  tasa guardada {tx.tasa_cambio}  -  {tx.cliente.nombre}  -  PENDIENTE")
print()
PY
    ;;

pagar)
    django_shell <<'PY'
import os, sys
from django.core.exceptions import ValidationError
from apps.divisas.models import TasaCambio
from apps.transacciones.models import Transaccion

pendientes = Transaccion.objects.filter(estado="PENDIENTE")
if os.environ["DEMO_TX_ID"]:
    tx = pendientes.filter(id=os.environ["DEMO_TX_ID"]).first()
    if tx is None:
        sys.exit(f"La transacción #{os.environ['DEMO_TX_ID']} no existe o ya no está pendiente.")
else:
    tx = pendientes.order_by("-id").first()
if tx is None:
    sys.exit("No hay ninguna transacción pendiente. Creá una con: ./scripts/demo_cancelacion.sh crear")

vigente = TasaCambio.objects.activa_para(tx.moneda.codigo)
tasa_vigente = None
if vigente:
    tasa_vigente = vigente.tasa_para(tx.tipo)

print()
print(f"  Confirmando el pago de la transacción #{tx.id}")
print(f"  Tasa guardada al iniciar .. {tx.tasa_cambio}")
print(f"  Tasa vigente ahora ........ {tasa_vigente}")
print()
try:
    tx.confirmar()
    print(f"  RESULTADO: {tx.estado}")
    print("  La cotización no cambió: el pago se confirma.")
except ValidationError as e:
    tx.refresh_from_db()
    print(f"  RESULTADO: {tx.estado}")
    print(f"  {e.messages[0]}")
print()
PY
    ;;
esac
