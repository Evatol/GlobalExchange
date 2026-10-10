"""Carga los datos de negocio necesarios para probar el sistema de punta a
punta: monedas con su cotización, métodos de pago, clientes de cada
categoría (para ver la comisión diferenciada y el límite por operación), la
asociación de ``cliente_demo`` a uno de ellos, y sus cuentas en el banco
simulado con un medio de pago por cada tipo (efectivo, cuenta, billetera y
tarjeta de crédito).

Para el módulo de caja: la moneda local (guaraní), las denominaciones de
billetes, una sucursal con ``cajero_demo`` asignado y su caja abierta con una
carga inicial de billetes (solo la primera vez: si ya se abrió o cerró, no se
toca).

Complementa a ``seed_usuarios_demo``, que crea los usuarios en Keycloak:
ese deja las credenciales listas, este deja con qué operar.

Es **idempotente**: correrlo de nuevo no duplica nada.

Uso::

    python manage.py seed_datos_demo
    python manage.py seed_datos_demo --usuario otro_usuario
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from django.contrib.auth.models import Group, User

from apps.banco import services as banco
from apps.banco.models import CuentaBancaria
from apps.caja import services as caja_services
from apps.caja.models import AsignacionCajero, Billete, Caja, Sucursal
from apps.divisas.models import Moneda, TasaCambio
from apps.transacciones.models import MedioPagoCliente, MetodoPago
from apps.usuarios.models import Cliente, Usuario

MONEDAS = [
    # (codigo, nombre, simbolo, tasa_compra, tasa_venta)
    ('USD', 'Dólar estadounidense', '$', Decimal('7300'), Decimal('7400')),
    ('EUR', 'Euro', '€', Decimal('7900'), Decimal('8050')),
    ('BRL', 'Real brasileño', 'R$', Decimal('1350'), Decimal('1420')),
]

# Moneda local: los importes de las operaciones están en guaraníes. Está en el
# catálogo porque la caja la necesita (``settings.MONEDA_LOCAL_CODIGO``), pero
# no tiene cotización: no se compra ni se vende.
MONEDA_LOCAL = ('PYG', 'Guaraní', '₲')

# Denominaciones de billetes por moneda, y cuántos de cada una tiene la caja demo.
DENOMINACIONES = {
    'PYG': [2000, 5000, 10000, 20000, 50000, 100000],
    'USD': [1, 5, 10, 20, 50, 100],
    'EUR': [5, 10, 20, 50, 100, 200, 500],
    'BRL': [2, 5, 10, 20, 50, 100, 200],
}
BILLETES_POR_DENOMINACION = 10
CAJERO_DEMO = 'cajero_demo'
SUCURSAL_DEMO = ('Casa Central', 'Asunción')

METODOS_PAGO = [
    ('Efectivo', MetodoPago.TIPO_EFECTIVO),
    ('Transferencia bancaria', MetodoPago.TIPO_TRANSFERENCIA),
    ('Billetera electrónica', MetodoPago.TIPO_BILLETERA),
    ('Tarjeta de crédito', MetodoPago.TIPO_TARJETA_CREDITO),
]

CLIENTES = [
    # (nombre, documento, categoria, preferencia de tipo de cambio)
    ('Comercial Uno', '80012345-6', Cliente.CATEGORIA_MAYORISTA, Cliente.PREFERENCIA_MAYORISTA),
    ('Comercial Dos', '80099999-1', Cliente.CATEGORIA_MINORISTA, Cliente.PREFERENCIA_ESTANDAR),
    ('Importadora Tres', '80077777-3', Cliente.CATEGORIA_VIP, Cliente.PREFERENCIA_PREFERENCIAL),
]

# Cuentas del banco del primer cliente y el medio de pago con el que las usa:
# (alias, método, número, entidad, tipo de cuenta, saldo, línea de crédito).
# La tarjeta tiene menos línea que el límite de un mayorista (1.000.000 Gs),
# para poder mostrar un pago rechazado por saldo insuficiente.
MEDIOS_DEL_CLIENTE = [
    ('Caja chica', 'Efectivo', 'EF-001', None, None, None, None),
    (
        'Cuenta Itaú', 'Transferencia bancaria', 'CA-1001', 'Banco Itaú',
        CuentaBancaria.TIPO_CUENTA, Decimal('5000000.00'), Decimal('0.00'),
    ),
    (
        'Tigo Money', 'Billetera electrónica', '0981-123456', 'Tigo Money',
        CuentaBancaria.TIPO_BILLETERA, Decimal('150000.00'), Decimal('0.00'),
    ),
    (
        'Visa Itaú', 'Tarjeta de crédito', '4111-0000-0000-1111', 'Banco Itaú',
        CuentaBancaria.TIPO_TARJETA_CREDITO, Decimal('0.00'), Decimal('500000.00'),
    ),
]


class Command(BaseCommand):
    help = (
        'Carga datos de demostración (monedas, cotizaciones, métodos de pago, '
        'clientes y su asociación) para poder probar el sistema. Idempotente.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--usuario',
            default='cliente_demo',
            help='Usuario a asociar al primer cliente (default: cliente_demo).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Monedas y cotizaciones:'))
        for codigo, nombre, simbolo, compra, venta in MONEDAS:
            moneda, creada = Moneda.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': nombre, 'simbolo': simbolo, 'estado': True},
            )
            tasa = TasaCambio.objects.filter(moneda=moneda, estado=True).first()
            if tasa is None:
                TasaCambio.objects.create(
                    moneda=moneda, tasa_compra=compra, tasa_venta=venta,
                    origen='Banco Central', estado=True,
                )
                detalle = f'compra {compra} / venta {venta}'
            else:
                detalle = f'ya tenía cotización ({tasa.tasa_compra} / {tasa.tasa_venta})'
            marca = 'creada' if creada else 'ya existía'
            self.stdout.write(f'  {codigo}: {marca}, {detalle}')

        self.stdout.write(self.style.MIGRATE_HEADING('Métodos de pago:'))
        metodos = {}
        for nombre, tipo in METODOS_PAGO:
            # update_or_create: corrige el tipo de los que se crearon cuando
            # el tipo era texto libre.
            metodo, creado = MetodoPago.objects.update_or_create(
                nombre=nombre, defaults={'tipo': tipo},
            )
            metodos[nombre] = metodo
            self.stdout.write(f'  {nombre}: {"creado" if creado else "ya existía"}')

        self.stdout.write(self.style.MIGRATE_HEADING('Clientes:'))
        clientes = []
        for nombre, doc, categoria, preferencia in CLIENTES:
            cliente, creado = Cliente.objects.get_or_create(
                documento=doc,
                defaults={
                    'nombre': nombre, 'tipo': 'JURIDICA', 'razon_social': f'{nombre} S.A.',
                    'categoria': categoria, 'preferencia_tipo_cambio': preferencia,
                },
            )
            clientes.append(cliente)
            self.stdout.write(
                f'  {cliente.nombre}: {"creado" if creado else "ya existía"} '
                f'({cliente.get_categoria_display()}, {_limite(cliente)})'
            )

        # El Usuario de negocio normalmente lo crea el backend OIDC en el primer
        # login. Lo creamos acá para poder dejar la asociación lista sin obligar
        # a entrar primero: si después inicia sesión, el backend reutiliza este
        # mismo registro (busca por username).
        username = options['usuario']
        usuario, creado = Usuario.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username}@example.com',
                'nombres': username.split('_')[0].capitalize(),
                'apellidos': 'Demo',
            },
        )
        principal = clientes[0]
        usuario.clientes.add(principal)
        self.stdout.write(self.style.MIGRATE_HEADING('Asociación usuario/cliente:'))
        self.stdout.write(
            f'  {username} ({"creado" if creado else "ya existía"}) -> {principal.nombre}'
        )

        self.stdout.write(self.style.MIGRATE_HEADING('Banco y medios de pago del cliente:'))
        for alias, metodo, numero, entidad, tipo_cuenta, saldo, linea in MEDIOS_DEL_CLIENTE:
            if tipo_cuenta is not None and banco.buscar_cuenta(numero) is None:
                banco.abrir_cuenta(
                    numero=numero, tipo=tipo_cuenta, entidad=entidad,
                    titular_documento=principal.documento, titular_nombre=principal.nombre,
                    saldo=saldo, linea_credito=linea,
                )
            medio, creado = MedioPagoCliente.objects.get_or_create(
                cliente=principal, metodo_pago=metodos[metodo], identificador=numero,
                defaults={'alias': alias, 'titular': principal.nombre, 'estado': True},
            )
            disponible = medio.disponible
            detalle = 'sin saldo' if disponible is None else f'disponible {banco.formatear_guaranies(disponible)}'
            self.stdout.write(f'  {medio.alias}: {"creado" if creado else "ya existía"} ({detalle})')

        self._cargar_caja_demo()

        self.stdout.write(self.style.SUCCESS(
            f'\nListo. {username} puede operar sobre "{principal.nombre}" '
            f'(comisión de {principal.get_preferencia_tipo_cambio_display()}, '
            f'{_limite(principal)}).'
        ))


    def _cargar_caja_demo(self):
        """Moneda local, denominaciones, sucursal, cajero y caja abierta."""
        self.stdout.write(self.style.MIGRATE_HEADING('Caja (sucursal, cajero y billetes):'))
        codigo, nombre, simbolo = MONEDA_LOCAL
        Moneda.objects.get_or_create(
            codigo=codigo, defaults={'nombre': nombre, 'simbolo': simbolo, 'estado': True},
        )
        for moneda_codigo, valores in DENOMINACIONES.items():
            moneda = Moneda.objects.filter(codigo=moneda_codigo).first()
            if moneda is None:
                continue
            for valor in valores:
                Billete.objects.get_or_create(moneda=moneda, denominacion=Decimal(valor))
        self.stdout.write(f'  Denominaciones: {Billete.objects.count()}')

        sucursal, _ = Sucursal.objects.get_or_create(
            nombre=SUCURSAL_DEMO[0], defaults={'direccion': SUCURSAL_DEMO[1]},
        )
        # El login con el grupo del rol cajero, como lo deja la sincronización
        # con Keycloak: sin él no se puede asignar a la sucursal (RF105).
        login, _ = User.objects.get_or_create(
            username=CAJERO_DEMO, defaults={'email': f'{CAJERO_DEMO}@example.com'},
        )
        login.groups.add(Group.objects.get_or_create(name='cajero')[0])
        cajero, _ = Usuario.objects.get_or_create(
            username=CAJERO_DEMO,
            defaults={
                'email': f'{CAJERO_DEMO}@example.com', 'nombres': 'Cajero', 'apellidos': 'Demo',
            },
        )
        AsignacionCajero.objects.get_or_create(sucursal=sucursal, usuario=cajero)
        caja, creada = Caja.objects.get_or_create(
            sucursal=sucursal, cajero=cajero,
            defaults={'saldo_inicial': Decimal('0'), 'saldo_actual': Decimal('0')},
        )
        if caja.fecha_apertura is None:
            carga = {
                b.id: BILLETES_POR_DENOMINACION for b in Billete.objects.filter(estado=True)
            }
            caja_services.abrir_caja(caja, cajero, carga)
            detalle = f'abierta con {BILLETES_POR_DENOMINACION} billetes de cada denominación'
        else:
            detalle = f'ya estaba {caja.estado.lower()}'
        self.stdout.write(f'  Caja #{caja.pk} de {CAJERO_DEMO} en {sucursal.nombre}: {detalle}')


def _limite(cliente):
    limite = cliente.limite_por_operacion
    if limite is None:
        return 'sin límite por operación'
    return f'límite por operación {banco.formatear_guaranies(limite)}'
