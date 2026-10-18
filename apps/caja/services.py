"""apps/caja/services.py - lógica de RF106 (inventario y arqueo de billetes).

Todas las funciones que tocan stock son atómicas y bloquean las filas que
modifican (select_for_update), así que dos operaciones simultáneas sobre la
misma caja no pueden dejar el stock inconsistente.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from apps.divisas.models import Moneda
from apps.transacciones.models import MetodoPago, Transaccion

from apps.notificaciones.models import Notificaciones
from apps.usuarios.models import Usuario

from .models import (
    Arqueo, Billete, Caja, CierreCaja, DetalleArqueo, DetalleCierre,
    LimiteStock, MovimientoBillete, StockBillete, Terminal,
)

CERO = Decimal('0')


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normalizar(items, nombre):
    """Acepta {billete_id: cantidad}; descarta ceros y rechaza negativos o
    valores no numéricos."""
    limpio = {}
    for billete_id, cantidad in (items or {}).items():
        try:
            billete_id, cantidad = int(billete_id), int(cantidad)
        except (TypeError, ValueError):
            raise ValidationError(f'Valores no numéricos en {nombre}.')
        if cantidad < 0:
            raise ValidationError(f'Cantidad negativa en {nombre}.')
        if cantidad > 0:
            limpio[billete_id] = cantidad
    return limpio


def _moneda_local():
    """Moneda en la que están expresados los importes de Transaccion (guaraní).
    Se toma de settings.MONEDA_LOCAL_CODIGO (por defecto 'PYG')."""
    codigo = getattr(settings, 'MONEDA_LOCAL_CODIGO', 'PYG')
    moneda = Moneda.objects.filter(codigo__iexact=codigo).first()
    if moneda is None:
        raise ValidationError(
            f'No existe la moneda local ({codigo}) en el catálogo de monedas.'
        )
    return moneda


def caja_abierta_de(usuario):
    """Caja abierta del cajero (la restricción de la base garantiza una sola)."""
    caja = Caja.objects.filter(cajero=usuario, estado='ABIERTA').first()
    if caja is None:
        raise ValidationError('No tenés una caja abierta asignada.')
    return caja


def _sincronizar_caja_de_la_terminal(terminal):
    """La caja de una terminal está abierta mientras la terminal esté activa y cerrada si
    no: así su stock cuenta como disponible solo cuando la terminal puede operar (las
    comprobaciones de stock y la anulación trabajan sobre cajas abiertas)."""
    caja = terminal.caja
    ahora = timezone.now()
    if terminal.estado == Terminal.ACTIVA and caja.estado != 'ABIERTA':
        caja.estado, caja.fecha_apertura, caja.fecha_cierre = 'ABIERTA', ahora, None
        caja.save(update_fields=['estado', 'fecha_apertura', 'fecha_cierre'])
    elif terminal.estado != Terminal.ACTIVA and caja.estado == 'ABIERTA':
        caja.estado, caja.fecha_cierre = 'CERRADA', ahora
        caja.save(update_fields=['estado', 'fecha_cierre'])


@transaction.atomic
def crear_terminal(nombre, sucursal, estado, stock_inicial=None):
    """Crea una terminal, su caja y el inventario inicial como una unidad. La caja nace
    abierta si la terminal está activa (ver ``_sincronizar_caja_de_la_terminal``)."""
    if not sucursal.estado:
        raise ValidationError({'sucursal': 'La sucursal debe estar activa.'})

    stock_inicial = _normalizar(stock_inicial, 'stock inicial')
    billetes = {
        billete.pk: billete
        for billete in Billete.objects.filter(pk__in=stock_inicial, estado=True)
    }
    faltantes = set(stock_inicial) - set(billetes)
    if faltantes:
        raise ValidationError(
            f'Denominaciones inexistentes o inactivas: {sorted(faltantes)}'
        )

    caja = Caja.objects.create(
        sucursal=sucursal,
        cajero=None,
        saldo_inicial=0,
        saldo_actual=0,
    )
    terminal = Terminal.objects.create(
        nombre=nombre, sucursal=sucursal, estado=estado, caja=caja
    )
    _sincronizar_caja_de_la_terminal(terminal)

    denominaciones_activas = list(Billete.objects.filter(estado=True))
    StockBillete.objects.bulk_create([
        StockBillete(
            caja=caja,
            billete=billete,
            cantidad=stock_inicial.get(billete.pk, 0),
        )
        for billete in denominaciones_activas
    ])
    MovimientoBillete.objects.bulk_create([
        MovimientoBillete(
            caja=caja,
            billete=billetes[billete_id],
            tipo='ENTRADA',
            cantidad=cantidad,
        )
        for billete_id, cantidad in stock_inicial.items()
        if cantidad > 0
    ])
    return terminal


@transaction.atomic
def actualizar_terminal(terminal, cambios):
    """Actualiza datos de una terminal, manteniendo sucursal y caja coherentes."""
    terminal = Terminal.objects.select_for_update().select_related('caja', 'sucursal').get(
        pk=terminal.pk
    )
    sucursal = cambios.get('sucursal', terminal.sucursal)
    estado = cambios.get('estado', terminal.estado)
    if estado == Terminal.ACTIVA and not sucursal.estado:
        raise ValidationError({'estado': 'No se puede activar una terminal en una sucursal inactiva.'})
    if sucursal != terminal.sucursal and (
        terminal.caja.movimientos_billetes.filter(transaccion__isnull=False).exists()
        or terminal.caja.cierres.exists()
        or terminal.caja.arqueos.exists()
    ):
        raise ValidationError({
            'sucursal': 'No se puede cambiar la sucursal de una terminal con operaciones o cierres.'
        })

    terminal.nombre = cambios.get('nombre', terminal.nombre)
    terminal.sucursal = sucursal
    terminal.estado = estado
    terminal.save()
    if terminal.caja.sucursal_id != sucursal.pk:
        terminal.caja.sucursal = sucursal
        terminal.caja.save(update_fields=['sucursal'])
    _sincronizar_caja_de_la_terminal(terminal)
    return terminal


def validar_terminal_operativa(terminal):
    """Rechaza el inicio en terminales no operativas o de sucursales inactivas."""
    if terminal.estado != Terminal.ACTIVA:
        estados = dict(Terminal.ESTADOS)
        raise ValidationError(
            f'Terminal no operativa: se encuentra {estados[terminal.estado].lower()}.'
        )
    if not terminal.sucursal.estado:
        raise ValidationError('Terminal no operativa: la sucursal está inactiva.')
    return terminal


# ---------------------------------------------------------------------------
# Alertas de stock mínimo y máximo (RF107)
# ---------------------------------------------------------------------------

def _formato(valor):
    """``Decimal('1847.00')`` -> ``'1.847'``; ``Decimal('0.50')`` -> ``'0,50'``."""
    texto = f'{Decimal(valor):,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return texto[:-3] if texto.endswith(',00') else texto


def _saldos_por_moneda(caja, moneda_ids):
    """``{moneda_id: stock}`` de la caja: suma de denominación × cantidad, en la
    propia moneda. Una moneda sin billetes en la caja vale 0."""
    saldos = {moneda_id: CERO for moneda_id in moneda_ids}
    filas = StockBillete.objects.filter(
        caja=caja, billete__moneda_id__in=moneda_ids
    ).select_related('billete')
    for fila in filas:
        saldos[fila.billete.moneda_id] += fila.billete.denominacion * fila.cantidad
    return saldos


def alertas_de_stock(caja, moneda_ids=None):
    """Alertas de stock vigentes de la caja, según los límites de ``LimiteStock``.

    Devuelve una lista de ``{'moneda', 'moneda_id', 'nivel', 'saldo', 'limite',
    'mensaje'}``: una por cada moneda cuyo stock llegó o pasó el mínimo
    (``BAJO``) o el máximo (``ALTO``). Las monedas sin límite configurado, o
    dentro de sus límites, no aparecen. ``moneda_ids`` acota el cálculo a esas
    monedas. Se calcula siempre desde el stock actual, así que no hay un estado
    de alerta aparte que pueda quedar desactualizado.
    """
    limites = LimiteStock.objects.select_related('moneda')
    if moneda_ids is not None:
        limites = limites.filter(moneda_id__in=moneda_ids)
    limites = list(limites)
    if not limites:
        return []

    saldos = _saldos_por_moneda(caja, [limite.moneda_id for limite in limites])
    alertas = []
    for limite in limites:
        saldo = saldos[limite.moneda_id]
        nivel = limite.nivel(saldo)
        if nivel is None:
            continue
        valor = limite.minimo if nivel == LimiteStock.NIVEL_BAJO else limite.maximo
        lado = 'mínimo' if nivel == LimiteStock.NIVEL_BAJO else 'máximo'
        alertas.append({
            'moneda': limite.moneda.codigo,
            'moneda_id': limite.moneda_id,
            'nivel': nivel,
            'saldo': saldo,
            'limite': valor,
            'mensaje': (
                f'hay {_formato(saldo)} {limite.moneda.codigo} en billetes y el '
                f'{lado} configurado es {_formato(valor)}.'
            ),
        })
    return alertas


def _destinatarios_de_alerta(caja):
    """``Usuario`` que reciben el aviso: los administradores y el cajero de la caja.
    Quien todavía no tiene su ``Usuario`` de negocio (se crea en el primer login)
    no recibe nada: no hay a quién asociarle la notificación."""
    from django.contrib.auth.models import User
    from django.db.models import Q

    usernames = set(
        User.objects.filter(Q(is_superuser=True) | Q(groups__name='administrador'))
        .values_list('username', flat=True)
    )
    if caja.cajero_id:
        usernames.add(caja.cajero.username)
    return list(Usuario.objects.filter(username__in=usernames))


def _notificar_alertas_nuevas(caja, antes, despues):
    """Crea una notificación por cada alerta que **apareció o cambió de nivel**
    entre ``antes`` y ``despues`` (``{moneda_id: alerta}``).

    Solo se avisa al cruzar el límite: si el stock ya estaba bajo y sigue bajo,
    no se repite el aviso en cada operación (la alerta sigue visible en Mi Caja
    mientras dure). Si vuelve a la normalidad y después cruza otra vez, avisa de
    nuevo. Corre dentro de la transacción del movimiento: si este se revierte,
    el aviso también.
    """
    nuevas = [
        alerta for moneda_id, alerta in despues.items()
        if antes.get(moneda_id, {}).get('nivel') != alerta['nivel']
    ]
    if not nuevas:
        return
    destinatarios = _destinatarios_de_alerta(caja)
    donde = f'Caja #{caja.pk} ({caja.sucursal.nombre}'
    donde += f', cajero {caja.cajero.username})' if caja.cajero_id else ')'
    for alerta in nuevas:
        estado = 'bajo' if alerta['nivel'] == LimiteStock.NIVEL_BAJO else 'alto'
        for usuario in destinatarios:
            Notificaciones.objects.create(
                usuario=usuario,
                titulo=f'Stock de billetes {estado}: {alerta["moneda"]}',
                mensaje=f'{donde}: {alerta["mensaje"]}',
                tipo='stock_billetes',
            )


# ---------------------------------------------------------------------------
# Stock y movimientos
# ---------------------------------------------------------------------------

@transaction.atomic
def registrar_movimientos_billetes(caja, usuario, transaccion, recibidos, entregados):
    """Registra billetes recibidos (ENTRADA) y entregados (SALIDA) en la caja y
    actualiza su stock. Todo o nada.

    recibidos / entregados: {billete_id: cantidad}. Con transaccion=None sirve
    para la carga inicial de la apertura. Dentro de una misma operación se
    puede dar vuelto con billetes recién recibidos.
    """
    caja = Caja.objects.select_for_update().get(pk=caja.pk)
    if caja.estado != 'ABIERTA':
        raise ValidationError('La caja debe estar abierta para operar.')

    recibidos = _normalizar(recibidos, 'recibidos')
    entregados = _normalizar(entregados, 'entregados')
    if not recibidos and not entregados:
        raise ValidationError('Debe registrar al menos un billete.')

    ids = sorted(set(recibidos) | set(entregados))  # orden fijo: evita deadlocks
    billetes = {b.id: b for b in Billete.objects.filter(id__in=ids, estado=True)}
    faltantes = set(ids) - set(billetes)
    if faltantes:
        raise ValidationError(
            f'Denominaciones inexistentes o inactivas: {sorted(faltantes)}'
        )

    # RF107: estado de las alertas antes de mover los billetes, para avisar solo
    # de las que aparecen con este movimiento.
    monedas_afectadas = {billetes[i].moneda_id for i in ids}
    alertas_antes = {
        a['moneda_id']: a for a in alertas_de_stock(caja, monedas_afectadas)
    }

    for billete_id in ids:
        billete = billetes[billete_id]
        stock, _ = StockBillete.objects.select_for_update().get_or_create(
            caja=caja, billete=billete
        )
        entra = recibidos.get(billete_id, 0)
        sale = entregados.get(billete_id, 0)
        if sale > stock.cantidad + entra:
            raise ValidationError(
                f'Stock insuficiente de {billete}: hay {stock.cantidad}, se piden {sale}.'
            )
        stock.cantidad += entra - sale
        stock.save(update_fields=['cantidad'])

        for tipo, cantidad in (('ENTRADA', entra), ('SALIDA', sale)):
            if cantidad:
                MovimientoBillete.objects.create(
                    caja=caja, billete=billete, usuario=usuario,
                    transaccion=transaccion, tipo=tipo, cantidad=cantidad,
                )

    alertas_despues = {
        a['moneda_id']: a for a in alertas_de_stock(caja, monedas_afectadas)
    }
    _notificar_alertas_nuevas(caja, alertas_antes, alertas_despues)


@transaction.atomic
def abrir_caja(caja, usuario, carga_inicial=None):
    """Abre la caja y, si se indica, carga el efectivo inicial por denominación
    ({billete_id: cantidad}) como ENTRADAs sin transacción. `usuario` es quien
    la abre (cajero o administrador)."""
    caja = Caja.objects.select_for_update().get(pk=caja.pk)
    if caja.estado == 'ABIERTA':
        raise ValidationError('La caja ya está abierta.')
    if caja.cajero_id is None:
        raise ValidationError('La caja no tiene un cajero asignado.')
    caja.clean()
    if Caja.objects.filter(cajero_id=caja.cajero_id, estado='ABIERTA').exclude(pk=caja.pk).exists():
        raise ValidationError('El cajero ya tiene otra caja abierta.')

    caja.estado = 'ABIERTA'
    caja.fecha_apertura = timezone.now()
    caja.fecha_cierre = None
    caja.save(update_fields=['estado', 'fecha_apertura', 'fecha_cierre'])

    if carga_inicial:
        registrar_movimientos_billetes(caja, usuario, None, carga_inicial, None)
    return caja


# ---------------------------------------------------------------------------
# Operación presencial (cajero + cliente en el mostrador)
# ---------------------------------------------------------------------------

def _flujo_esperado(transaccion, local):
    """Neto esperado por moneda para la caja (recibido - entregado)."""
    t = transaccion
    if t.moneda_id == local.id:
        raise ValidationError('La divisa de la operación no puede ser la moneda local.')
    if t.tipo == 'COMPRA':   # el cliente paga guaraníes y se lleva la divisa
        return {local.id: t.monto_total, t.moneda_id: -t.cantidad}
    if t.tipo == 'VENTA':    # el cliente entrega la divisa y recibe guaraníes
        return {t.moneda_id: t.cantidad, local.id: -t.monto_total}
    # CAMBIO: entrega `cantidad` de moneda y recibe `cantidad_destino`
    return {t.moneda_id: t.cantidad, t.moneda_destino_id: -t.cantidad_destino}


def _neto_por_moneda(recibidos, entregados):
    ids = set(recibidos) | set(entregados)
    billetes = {b.id: b for b in Billete.objects.filter(id__in=ids, estado=True)}
    faltantes = ids - set(billetes)
    if faltantes:
        raise ValidationError(
            f'Denominaciones inexistentes o inactivas: {sorted(faltantes)}'
        )
    neto = {}
    for items, signo in ((recibidos, 1), (entregados, -1)):
        for billete_id, cantidad in items.items():
            b = billetes[billete_id]
            neto[b.moneda_id] = neto.get(b.moneda_id, CERO) + signo * b.denominacion * cantidad
    return neto


def validar_billetes_de_operacion(transaccion, recibidos, entregados):
    """Verifica que los billetes cargados por el cajero cubran la operación.

    Regla (a confirmar con el negocio): por cada moneda, el neto de billetes
    (recibido - entregado) debe coincidir con el esperado con una tolerancia
    de media denominación mínima activa de esa moneda, porque los importes
    tienen centavos que no se pueden pagar con billetes.
    """
    local = _moneda_local()
    esperado = _flujo_esperado(transaccion, local)
    real = _neto_por_moneda(recibidos, entregados)

    moneda_ids = set(esperado) | set(real)
    monedas = Moneda.objects.in_bulk(moneda_ids)
    for moneda_id in moneda_ids:
        codigo = monedas[moneda_id].codigo
        menor = Billete.objects.filter(
            moneda_id=moneda_id, estado=True
        ).aggregate(m=Min('denominacion'))['m']
        if menor is None:
            raise ValidationError(f'No hay denominaciones cargadas para {codigo}.')
        exp = esperado.get(moneda_id, CERO)
        got = real.get(moneda_id, CERO)
        if abs(got - exp) > menor / 2:
            raise ValidationError(
                f'Los billetes de {codigo} no coinciden con la operación: '
                f'neto esperado (recibido - entregado) {exp}, cargado {got}.'
            )


def operaciones_de_la_caja(caja, limite=15):
    """Las últimas operaciones que movieron billetes en esta caja (las que se
    atendieron en ella), la más reciente primero."""
    return list(
        Transaccion.objects.filter(movimientos_billetes__caja=caja)
        .select_related('cliente', 'moneda', 'moneda_destino', 'metodo_pago')
        .distinct().order_by('-fecha_hora', '-id')[:limite]
    )


def anular_operacion_en_efectivo(caja, transaccion_id):
    """Anula una operación en efectivo atendida en ``caja`` (E4-196) y devuelve
    la transacción. Solo se pueden anular las operaciones de la propia caja
    abierta del cajero: una operación de otra caja (o inexistente) responde
    igual, para no revelar su existencia. Ver ``Transaccion.anular_operacion``
    para qué se revierte y cuándo se rechaza.
    """
    transaccion = (
        Transaccion.objects.select_related('metodo_pago')
        .filter(pk=transaccion_id, movimientos_billetes__caja=caja).distinct().first()
    )
    if transaccion is None:
        raise ValidationError('No existe esa operación en tu caja.')
    transaccion.anular_operacion(usuario=caja.cajero)
    return transaccion


def registrar_operacion_presencial(
    *, caja, usuario, cliente, tipo, moneda_codigo, cantidad,
    recibidos=None, entregados=None, moneda_destino_codigo=None,
):
    """Registra la operación y conserva como FALLIDA cualquier intento que
    falle al procesar caja. Los movimientos fallidos se revierten primero.
    """
    referencia = {}
    try:
        return _registrar_operacion_presencial_atomica(
            caja=caja, usuario=usuario, cliente=cliente, tipo=tipo,
            moneda_codigo=moneda_codigo, cantidad=cantidad,
            recibidos=recibidos, entregados=entregados,
            moneda_destino_codigo=moneda_destino_codigo,
            referencia=referencia,
        )
    except ValidationError as exc:
        transaccion = referencia.get('transaccion')
        if transaccion is not None:
            transaccion.estado = 'FALLIDA'
            transaccion.observacion = ' '.join(exc.messages)
            transaccion.save()
        raise


@transaction.atomic
def _registrar_operacion_presencial_atomica(
    *, caja, usuario, cliente, tipo, moneda_codigo, cantidad,
    recibidos=None, entregados=None, moneda_destino_codigo=None, referencia=None,
):
    """Compra, venta o cambio de divisas en el mostrador, pagado en efectivo.

    El cajero (`usuario`, un Usuario de negocio) atiende a `cliente`, carga los
    billetes que recibió y entregó, y la operación se confirma en el acto.
    Todo o nada: si algo falla (stock, billetes que no cierran, límite del
    cliente, cotización que cambió) no queda nada guardado, ni siquiera una
    transacción CANCELADA/FALLIDA como en el flujo digital.

    Registro automático (E4-101): si no se indican ``recibidos`` ni
    ``entregados``, el sistema arma solo el desglose por denominación
    (``desglose_automatico``) y registra los movimientos y el stock. Si se
    indican, se respeta lo que cargó el cajero (por ejemplo, si el cliente
    pagó con otros billetes que los sugeridos).
    """
    # Import diferido: reutiliza la misma regla de tasas y comisión que la
    # operación digital (hoy es un helper privado de transacciones.views;
    # conviene moverlo a un services.py de esa app).
    from apps.transacciones.views import _preparar_transaccion

    if caja.cajero_id != usuario.id:
        raise ValidationError('Esta caja no está asignada a este cajero.')
    if not cliente.estado:
        raise ValidationError('El cliente está inactivo.')

    transaccion, error = _preparar_transaccion(
        cliente, str(tipo).upper(), moneda_codigo, cantidad, moneda_destino_codigo,
    )
    if referencia is not None:
        referencia['transaccion'] = transaccion
    if error:
        raise ValidationError(error)

    efectivo = MetodoPago.objects.filter(
        tipo=MetodoPago.TIPO_EFECTIVO, estado=True
    ).first()
    if efectivo is None:
        raise ValidationError('No hay un método de pago en efectivo activo en el catálogo.')

    transaccion.usuario = usuario
    transaccion.metodo_pago = efectivo
    transaccion.modalidad = 'PRESENCIAL'

    error_limite = transaccion.validar_limite_cliente()
    if error_limite:
        raise ValidationError(error_limite)

    if recibidos is None and entregados is None:
        recibidos, entregados = desglose_automatico(caja, transaccion)
    recibidos = _normalizar(recibidos, 'recibidos')
    entregados = _normalizar(entregados, 'entregados')
    validar_billetes_de_operacion(transaccion, recibidos, entregados)

    transaccion.save()  # PENDIENTE
    registrar_movimientos_billetes(caja, usuario, transaccion, recibidos, entregados)
    transaccion.confirmar()  # EXITOSA, o ValidationError y se revierte todo
    return transaccion

# ---------------------------------------------------------------------------
# Vista Previa que muestra al cajero cuanto tiene que recibir y entregar antes de cargar los billetes
# ---------------------------------------------------------------------------

def previsualizar_operacion_presencial(
    *, cliente, tipo, moneda_codigo, cantidad, moneda_destino_codigo=None,
):
    """Calcula, sin guardar nada, una operación presencial.

    Devuelve (transaccion_armada, neto_esperado). ``neto_esperado`` es
    {codigo_de_moneda: importe}: positivo = la caja recibe esa cantidad,
    negativo = la caja entrega. Sirve para que el cajero sepa qué billetes
    tiene que pedir y dar antes de cargarlos.
    """
    # Import diferido, mismo motivo que en registrar_operacion_presencial.
    from apps.transacciones.views import _preparar_transaccion

    if not cliente.estado:
        raise ValidationError('El cliente está inactivo.')

    transaccion, error = _preparar_transaccion(
        cliente, str(tipo).upper(), moneda_codigo, cantidad, moneda_destino_codigo,
    )
    if error:
        raise ValidationError(error)

    error_limite = transaccion.validar_limite_cliente()
    if error_limite:
        raise ValidationError(error_limite)

    esperado = _flujo_esperado(transaccion, _moneda_local())
    monedas = Moneda.objects.in_bulk(esperado.keys())
    return transaccion, {monedas[k].codigo: v for k, v in esperado.items()}


# ---------------------------------------------------------------------------
# Desglose automático en billetes (E4-101)
# ---------------------------------------------------------------------------

def desglose_de_monto(moneda_id, monto, disponible=None):
    """Billetes de ``moneda_id`` que suman ``monto``: ``{billete_id: cantidad}``.

    Va de la denominación más grande a la más chica. ``disponible``
    (``{billete_id: cantidad}``) limita lo que se puede entregar: al recibir no
    se pasa, porque el cliente puede traer cualquier cantidad. Como los importes
    tienen centavos que no se pagan con billetes, lo que sobra por debajo de la
    denominación mínima se redondea al billete mínimo más cercano: el desvío
    nunca pasa de media denominación mínima, que es la misma tolerancia con la
    que ``validar_billetes_de_operacion`` acepta la operación.

    Lanza ``ValidationError`` si no hay denominaciones cargadas o si con lo
    disponible no se llega a cubrir el monto.
    """
    billetes = list(Billete.objects.filter(moneda_id=moneda_id, estado=True).order_by('-denominacion'))
    if not billetes:
        codigo = Moneda.objects.filter(pk=moneda_id).values_list('codigo', flat=True).first()
        raise ValidationError(f'No hay denominaciones cargadas para {codigo}.')

    resultado, restante = {}, Decimal(monto)
    for billete in billetes:
        cantidad = int(restante // billete.denominacion)
        if disponible is not None:
            cantidad = min(cantidad, disponible.get(billete.id, 0))
        if cantidad > 0:
            resultado[billete.id] = cantidad
            restante -= cantidad * billete.denominacion

    menor = billetes[-1]
    if restante >= menor.denominacion / 2:
        queda_uno = disponible is None or disponible.get(menor.id, 0) > resultado.get(menor.id, 0)
        if restante >= menor.denominacion or not queda_uno:
            raise ValidationError(
                f'No hay billetes suficientes de {menor.moneda.codigo} para cubrir {monto}.'
            )
        resultado[menor.id] = resultado.get(menor.id, 0) + 1
    return resultado


def desglose_automatico(caja, transaccion):
    """``(recibidos, entregados)`` de una operación presencial, calculados por el
    sistema: lo que la caja recibe en cada moneda se desglosa sin límite, y lo
    que entrega, con el stock que tiene la caja."""
    esperado = _flujo_esperado(transaccion, _moneda_local())
    stock = {s.billete_id: s.cantidad for s in StockBillete.objects.filter(caja=caja)}
    recibidos, entregados = {}, {}
    for moneda_id, monto in esperado.items():
        if monto > 0:
            recibidos.update(desglose_de_monto(moneda_id, monto))
        elif monto < 0:
            entregados.update(desglose_de_monto(moneda_id, -monto, stock))
    return recibidos, entregados


def sugerir_billetes(caja, transaccion):
    """Lo que el cajero tiene que pedir y dar, legible, para la vista previa:
    ``{'recibir': [...], 'entregar': [...], 'advertencia': str | None}``. Si con
    el stock de la caja no se puede cubrir, devuelve la advertencia en vez de
    fallar, para que el cajero lo sepa antes de empezar."""
    try:
        recibidos, entregados = desglose_automatico(caja, transaccion)
    except ValidationError as exc:
        return {'recibir': [], 'entregar': [], 'advertencia': ' '.join(exc.messages)}

    def detalle(cantidades):
        billetes = Billete.objects.filter(id__in=cantidades).select_related('moneda')
        return [
            {
                'moneda': b.moneda.codigo, 'billete_id': b.id,
                'denominacion': b.denominacion, 'cantidad': cantidades[b.id],
                'subtotal': b.denominacion * cantidades[b.id],
            }
            for b in sorted(billetes, key=lambda b: (b.moneda.codigo, -b.denominacion))
        ]

    return {'recibir': detalle(recibidos), 'entregar': detalle(entregados), 'advertencia': None}


# ---------------------------------------------------------------------------
# Balance y cierre de caja (E4-100)
# ---------------------------------------------------------------------------

def balance_caja(caja):
    """Balance de la sesión actual de la caja (desde que se abrió), por moneda.

    Cada fila tiene: ``saldo_al_abrir`` (lo que había de la sesión anterior),
    ``carga_inicial`` (lo que se cargó al abrir u otros movimientos sin
    operación), ``recibido`` y ``entregado`` por operaciones, y ``saldo_actual``
    (el stock del sistema). Siempre cierra: saldo_al_abrir + carga_inicial +
    recibido - entregado = saldo_actual. Todo se calcula desde el stock y los
    movimientos, que son lo único que lo modifica, así que no hay un saldo
    aparte que pueda desalinearse.

    Si la caja está cerrada, es el balance de la última sesión.
    """
    filas = {}

    def fila(moneda):
        return filas.setdefault(moneda.id, {
            'moneda': moneda.codigo, 'moneda_id': moneda.id,
            'saldo_al_abrir': CERO, 'carga_inicial': CERO,
            'recibido': CERO, 'entregado': CERO, 'saldo_actual': CERO,
        })

    for stock in StockBillete.objects.filter(caja=caja).select_related('billete__moneda'):
        fila(stock.billete.moneda)['saldo_actual'] += stock.billete.denominacion * stock.cantidad

    operaciones = set()
    if caja.fecha_apertura is not None:
        movimientos = MovimientoBillete.objects.filter(
            caja=caja, fecha_hora__gte=caja.fecha_apertura
        ).select_related('billete__moneda')
        for mov in movimientos:
            valor = mov.billete.denominacion * mov.cantidad
            f = fila(mov.billete.moneda)
            if mov.transaccion_id is None:
                f['carga_inicial'] += valor if mov.tipo == 'ENTRADA' else -valor
            else:
                operaciones.add(mov.transaccion_id)
                f['recibido' if mov.tipo == 'ENTRADA' else 'entregado'] += valor

    for f in filas.values():
        f['saldo_al_abrir'] = (
            f['saldo_actual'] - f['carga_inicial'] - f['recibido'] + f['entregado']
        )
    return {
        'caja': caja.pk,
        'estado': caja.estado,
        'fecha_apertura': caja.fecha_apertura,
        'fecha_cierre': caja.fecha_cierre,
        'operaciones': len(operaciones),
        'monedas': sorted(filas.values(), key=lambda f: f['moneda']),
        'alertas': alertas_de_stock(caja),
    }


@transaction.atomic
def cerrar_caja(caja, usuario, contados=None):
    """Cierra la caja y guarda el balance de la sesión (``CierreCaja``).

    ``contados`` es opcional: ``{moneda_id: {billete_id: cantidad}}``. Por cada
    moneda contada se registra un arqueo y su diferencia queda en el cierre;
    las monedas que no se cuentan quedan "sin contar". Una diferencia no
    impide cerrar: se registra. El stock queda como está: es el remanente con
    el que se abre la próxima sesión.

    ``usuario`` es quien cierra (el cajero o un administrador).
    """
    caja = Caja.objects.select_for_update().get(pk=caja.pk)
    if caja.estado != 'ABIERTA':
        raise ValidationError('La caja no está abierta.')

    arqueos = {}
    for moneda_id, cantidades in (contados or {}).items():
        try:
            moneda = Moneda.objects.filter(pk=int(moneda_id)).first()
        except (TypeError, ValueError):
            moneda = None
        if moneda is None:
            raise ValidationError(f'Moneda inexistente: {moneda_id}.')
        arqueos[moneda.id] = registrar_arqueo(caja, usuario, moneda, cantidades)

    balance = balance_caja(caja)
    ahora = timezone.now()
    cierre = CierreCaja.objects.create(
        caja=caja, cajero=caja.cajero, cerrado_por=usuario,
        fecha_apertura=caja.fecha_apertura, fecha_cierre=ahora,
        operaciones=balance['operaciones'],
    )
    for f in balance['monedas']:
        arqueo = arqueos.get(f['moneda_id'])
        DetalleCierre.objects.create(
            cierre=cierre, moneda_id=f['moneda_id'],
            saldo_inicial=f['saldo_al_abrir'] + f['carga_inicial'],
            recibido=f['recibido'], entregado=f['entregado'], saldo_final=f['saldo_actual'],
            total_contado=arqueo.total_contado if arqueo else None,
            diferencia=arqueo.diferencia if arqueo else None,
        )

    caja.estado = 'CERRADA'
    caja.fecha_cierre = ahora
    caja.save(update_fields=['estado', 'fecha_cierre'])
    return cierre


# ---------------------------------------------------------------------------
# Inventario y arqueo
# ---------------------------------------------------------------------------

def inventario_por_moneda(caja):
    """Inventario de la caja agrupado por moneda, con subtotales y total.

    Incluye todas las denominaciones activas (con 0 si no hay stock) y las
    inactivas que todavía tengan stock.
    """
    stock = {s.billete_id: s.cantidad for s in StockBillete.objects.filter(caja=caja)}
    billetes = list(Billete.objects.filter(estado=True).select_related('moneda'))
    billetes += list(
        Billete.objects.filter(id__in=stock.keys(), estado=False).select_related('moneda')
    )

    por_moneda = {}
    for b in billetes:
        cantidad = stock.get(b.id, 0)
        grupo = por_moneda.setdefault(
            b.moneda_id,
            {'moneda': b.moneda.codigo, 'denominaciones': [], 'total': CERO},
        )
        subtotal = b.denominacion * cantidad
        grupo['denominaciones'].append({
            'billete_id': b.id,
            'denominacion': b.denominacion,
            'cantidad': cantidad,
            'subtotal': subtotal,
        })
        grupo['total'] += subtotal
    return list(por_moneda.values())


@transaction.atomic
def registrar_arqueo(caja, cajero, moneda, contados):
    """Guarda lo contado por el cajero y la diferencia contra lo esperado (el
    stock del sistema). No modifica el stock.

    contados: {billete_id: cantidad}. Una denominación que no venga se toma
    como 0 contado.
    """
    contados = _normalizar(contados, 'contados')

    # Bloquea el stock de esa caja/moneda para que lo esperado no cambie
    # mientras se calcula la diferencia.
    stocks = {
        s.billete_id: s.cantidad
        for s in StockBillete.objects.select_for_update().filter(
            caja=caja, billete__moneda=moneda
        )
    }
    billetes = {
        b.id: b
        for b in Billete.objects.filter(moneda=moneda)
        if b.estado or b.id in stocks
    }
    invalidos = set(contados) - set(billetes)
    if invalidos:
        raise ValidationError(
            f'Denominaciones que no corresponden a {moneda.codigo}: {sorted(invalidos)}'
        )

    total_esperado = CERO
    total_contado = CERO
    detalles = []
    for billete_id, billete in billetes.items():
        esperada = stocks.get(billete_id, 0)
        contada = contados.get(billete_id, 0)
        total_esperado += billete.denominacion * esperada
        total_contado += billete.denominacion * contada
        detalles.append(DetalleArqueo(
            billete=billete, cantidad_esperada=esperada, cantidad_contada=contada,
        ))

    arqueo = Arqueo.objects.create(
        caja=caja, cajero=cajero, moneda=moneda,
        total_esperado=total_esperado, total_contado=total_contado,
        diferencia=total_contado - total_esperado,
    )
    for d in detalles:
        d.arqueo = arqueo
    DetalleArqueo.objects.bulk_create(detalles)
    return arqueo


# ---------------------------------------------------------------------------
# Disponibilidad de billetes de la terminal (E4-195)
# ---------------------------------------------------------------------------

def _billetes_a_entregar(transaccion):
    """``{moneda_id: monto}`` que la terminal entrega en billetes en esta operación.

    * Compra: la divisa que compra el cliente.
    * Cambio: la divisa de destino.
    * Venta: guaraníes, pero solo si el cliente cobra en efectivo; si cobra en
      una cuenta o billetera no se entregan billetes.
    """
    t = transaccion
    if t.tipo == 'COMPRA':
        return {t.moneda_id: t.cantidad}
    if t.tipo == 'CAMBIO':
        return {t.moneda_destino_id: t.cantidad_destino}
    if t.metodo_pago.tipo != MetodoPago.TIPO_EFECTIVO:
        return {}
    try:
        return {_moneda_local().id: t.monto_total}
    except ValidationError:
        return {}  # sin moneda local en el catálogo no hay inventario de guaraníes


def _stock_en_cajas_abiertas(moneda_id):
    """``{billete_id: cantidad}`` sumando el stock de todas las cajas abiertas.
    Las cajas cerradas no cuentan: su efectivo no está disponible para operar."""
    disponible = {}
    filas = StockBillete.objects.filter(
        caja__estado='ABIERTA', billete__moneda_id=moneda_id
    )
    for fila in filas:
        disponible[fila.billete_id] = disponible.get(fila.billete_id, 0) + fila.cantidad
    return disponible


def evaluar_entrega_de_billetes(transaccion):
    """E4-195: ¿alcanza el stock de billetes para entregar lo que la operación requiere?

    Usa la misma regla de composición que el mostrador (``desglose_de_monto``:
    de la denominación mayor a la menor, con la tolerancia de media denominación
    mínima) sobre el stock total de las cajas abiertas.

    Devuelve ``None`` si alcanza, o ``(moneda_id, mensaje)`` con un mensaje claro
    para el usuario si no. Una moneda sin denominaciones cargadas no maneja
    inventario de billetes y no se evalúa.
    """
    for moneda_id, monto in _billetes_a_entregar(transaccion).items():
        if not Billete.objects.filter(moneda_id=moneda_id, estado=True).exists():
            continue
        try:
            desglose_de_monto(moneda_id, monto, _stock_en_cajas_abiertas(moneda_id))
        except ValidationError:
            codigo = Moneda.objects.filter(pk=moneda_id).values_list('codigo', flat=True).first()
            return moneda_id, (
                f'La terminal no cuenta con billetes suficientes de {codigo} '
                f'para entregar {_formato(monto)} {codigo}.'
            )
    return None


def notificar_falla_por_stock(transaccion, moneda_id):
    """E4-195: avisa que una operación quedó fallida por falta de billetes.

    1. Dispara la alerta de mínimo/máximo configurada (RF107) de esa moneda en
       cada caja abierta, aunque no sea nueva: la falla es el motivo del aviso.
       Si la moneda no tiene límite configurado o está dentro de sus límites,
       no hay alerta de RF107 que mandar.
    2. Avisa de la operación fallida a los administradores y a los cajeros de
       las cajas abiertas, siempre.

    Corre dentro de la transacción de ``Transaccion.confirmar()``: el estado
    FALLIDA y los avisos se guardan juntos.
    """
    cajas = list(Caja.objects.filter(estado='ABIERTA').select_related('sucursal', 'cajero'))

    for caja in cajas:
        vigentes = {a['moneda_id']: a for a in alertas_de_stock(caja, [moneda_id])}
        _notificar_alertas_nuevas(caja, {}, vigentes)

    # Una Caja vacía no tiene cajero: ``_destinatarios_de_alerta`` devuelve solo
    # a los administradores.
    destinatarios = {u.pk: u for u in _destinatarios_de_alerta(Caja())}
    for caja in cajas:
        destinatarios.update({u.pk: u for u in _destinatarios_de_alerta(caja)})

    codigo = Moneda.objects.filter(pk=moneda_id).values_list('codigo', flat=True).first()
    mensaje = (
        f'La operación #{transaccion.pk} ({transaccion.get_tipo_display()} de '
        f'{_formato(transaccion.cantidad)} {transaccion.moneda.codigo}) quedó fallida: '
        f'la terminal no cuenta con billetes suficientes de {codigo}.'
    )
    for usuario in destinatarios.values():
        Notificaciones.objects.create(
            usuario=usuario,
            titulo=f'Operación fallida por falta de billetes: {codigo}',
            mensaje=mensaje,
            tipo='stock_billetes',
        )
