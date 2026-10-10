"""Operaciones del banco simulado.

Es lo único que mueve saldos: el resto del sistema llama a estas funciones y
nunca toca ``CuentaBancaria.saldo`` directamente. ``debitar`` y ``acreditar``
no están expuestos como endpoints públicos (si lo estuvieran, un cliente
podría acreditarse plata a sí mismo): los usa ``Transaccion.confirmar()`` al
confirmar el pago de una operación. La API (``views.py``) solo deja consultar
cuentas y, al administrador, abrirlas y cargarles saldo.
"""

from decimal import Decimal

from django.db import transaction

from .models import CuentaBancaria, MovimientoBancario


class ErrorBancario(Exception):
    """El banco rechazó la operación. ``str(exc)`` es el mensaje para el usuario."""


class CuentaNoDisponible(ErrorBancario):
    """La cuenta no existe o está inactiva."""


class SaldoInsuficiente(ErrorBancario):
    """El disponible de la cuenta no alcanza para el débito.

    El mensaje no dice cuánto hay: como un banco real, solo rechaza. El saldo
    del cliente no lo ve la casa de cambio (y el mensaje queda guardado en el
    historial de la operación).
    """

    def __init__(self, cuenta, monto):
        self.cuenta = cuenta
        self.monto = monto
        super().__init__(f'Saldo insuficiente para pagar {formatear_guaranies(monto)}.')


def formatear_guaranies(monto):
    """``Decimal('96681.5')`` -> ``'96.681,50 Gs'``."""
    texto = f'{Decimal(monto):,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    return f'{texto} Gs'


def buscar_cuenta(numero):
    """La cuenta con ese número, o ``None``."""
    return CuentaBancaria.objects.filter(numero=numero).first()


def verificar_titular(numero, tipo, documento):
    """Comprueba que exista una cuenta activa con ese número y tipo, a nombre
    de ese documento. Devuelve ``None`` si está todo bien, o el mensaje de
    error."""
    cuenta = buscar_cuenta(numero)
    if cuenta is None or not cuenta.estado:
        return f'El banco no tiene una cuenta activa con el número {numero}.'
    if cuenta.tipo != tipo:
        return (
            f'La cuenta {numero} del banco es de tipo '
            f'"{cuenta.get_tipo_display()}", no coincide con el método de pago elegido.'
        )
    if cuenta.titular_documento != documento:
        return f'La cuenta {numero} no está a nombre del cliente.'
    return None


@transaction.atomic
def abrir_cuenta(*, numero, tipo, entidad, titular_documento, titular_nombre,
                 saldo=Decimal('0.00'), linea_credito=Decimal('0.00')):
    """Crea una cuenta. Una tarjeta arranca con toda su línea disponible.

    El saldo inicial queda registrado como primer movimiento, para que el
    historial de la cuenta siempre explique su saldo.
    """
    if tipo == CuentaBancaria.TIPO_TARJETA_CREDITO:
        saldo = linea_credito
    cuenta = CuentaBancaria(
        numero=numero, tipo=tipo, entidad=entidad,
        titular_documento=titular_documento, titular_nombre=titular_nombre,
        saldo=saldo, linea_credito=linea_credito,
    )
    cuenta.full_clean()
    cuenta.save()
    if cuenta.saldo > 0:
        concepto = 'Línea de crédito habilitada' if cuenta.es_tarjeta else 'Saldo inicial'
        _registrar(cuenta, MovimientoBancario.CREDITO, cuenta.saldo, concepto, '')
    return cuenta


@transaction.atomic
def debitar(numero, monto, concepto, referencia=''):
    """Descuenta ``monto`` del disponible. Lanza ``SaldoInsuficiente`` si no
    alcanza, sin modificar nada."""
    cuenta = _cuenta_bloqueada(numero, monto)
    if monto > cuenta.saldo:
        raise SaldoInsuficiente(cuenta, monto)
    cuenta.saldo -= monto
    cuenta.save(update_fields=['saldo'])
    return _registrar(cuenta, MovimientoBancario.DEBITO, monto, concepto, referencia)


@transaction.atomic
def acreditar(numero, monto, concepto, referencia=''):
    """Suma ``monto`` al disponible. En una tarjeta es un pago: devuelve
    crédito, pero nunca por encima de su línea."""
    cuenta = _cuenta_bloqueada(numero, monto)
    if cuenta.es_tarjeta and cuenta.saldo + monto > cuenta.linea_credito:
        raise ErrorBancario(
            f'El pago supera lo usado de la tarjeta '
            f'({formatear_guaranies(cuenta.credito_usado)}).'
        )
    cuenta.saldo += monto
    cuenta.save(update_fields=['saldo'])
    return _registrar(cuenta, MovimientoBancario.CREDITO, monto, concepto, referencia)


def _cuenta_bloqueada(numero, monto):
    """Valida el monto y devuelve la cuenta bloqueada (``select_for_update``)
    hasta el final de la transacción, para que dos pagos simultáneos no lean
    el mismo saldo."""
    if monto is None or monto <= 0:
        raise ErrorBancario('El monto debe ser mayor a cero.')
    cuenta = CuentaBancaria.objects.select_for_update().filter(numero=numero).first()
    if cuenta is None or not cuenta.estado:
        raise CuentaNoDisponible(f'La cuenta {numero} no existe o está inactiva en el banco.')
    return cuenta


def _registrar(cuenta, tipo, monto, concepto, referencia):
    return MovimientoBancario.objects.create(
        cuenta=cuenta, tipo=tipo, monto=monto, saldo_resultante=cuenta.saldo,
        concepto=concepto, referencia=referencia,
    )
