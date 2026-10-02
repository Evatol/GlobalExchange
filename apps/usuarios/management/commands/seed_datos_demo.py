"""Carga los datos de negocio necesarios para probar el sistema de punta a
punta: monedas con su cotización, métodos de pago, clientes de distinta
categoría (para ver la comisión diferenciada y el tope de límite) y la
asociación de ``cliente_demo`` a uno de ellos.

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

from apps.divisas.models import Moneda, TasaCambio
from apps.transacciones.models import MedioPagoCliente, MetodoPago
from apps.usuarios.models import Cliente, Usuario

MONEDAS = [
    # (codigo, nombre, simbolo, tasa_compra, tasa_venta)
    ('USD', 'Dólar estadounidense', '$', Decimal('7300'), Decimal('7400')),
    ('EUR', 'Euro', '€', Decimal('7900'), Decimal('8050')),
    ('BRL', 'Real brasileño', 'R$', Decimal('1350'), Decimal('1420')),
]

METODOS_PAGO = [
    ('Efectivo', 'CASH'),
    ('Transferencia bancaria', 'BANCO'),
    ('Billetera electrónica', 'WALLET'),
]

CLIENTES = [
    # (nombre, documento, categoria, preferencia, limite_compra, limite_venta)
    (
        'Comercial Uno', '80012345-6', Cliente.CATEGORIA_CORPORATIVO,
        Cliente.PREFERENCIA_MAYORISTA, Decimal('100000.00'), Decimal('0.00'),
    ),
    (
        'Comercial Dos', '80099999-1', Cliente.CATEGORIA_MINORISTA,
        Cliente.PREFERENCIA_ESTANDAR, Decimal('0.00'), Decimal('0.00'),
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
            metodo, creado = MetodoPago.objects.get_or_create(
                nombre=nombre, defaults={'tipo': tipo, 'estado': True},
            )
            metodos[nombre] = metodo
            self.stdout.write(f'  {nombre}: {"creado" if creado else "ya existía"}')

        self.stdout.write(self.style.MIGRATE_HEADING('Clientes:'))
        clientes = []
        for nombre, doc, categoria, preferencia, lim_compra, lim_venta in CLIENTES:
            cliente, creado = Cliente.objects.get_or_create(
                documento=doc,
                defaults={
                    'nombre': nombre, 'tipo': 'JURIDICA', 'razon_social': f'{nombre} S.A.',
                    'categoria': categoria, 'preferencia_tipo_cambio': preferencia,
                    'limite_compra': lim_compra, 'limite_venta': lim_venta,
                },
            )
            clientes.append(cliente)
            self.stdout.write(
                f'  {cliente.nombre}: {"creado" if creado else "ya existía"} '
                f'({cliente.get_preferencia_tipo_cambio_display()}, '
                f'límite de compra {cliente.limite_compra})'
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

        medio, creado = MedioPagoCliente.objects.get_or_create(
            cliente=principal, metodo_pago=metodos['Efectivo'], identificador='EF-001',
            defaults={'alias': 'Caja chica', 'titular': principal.nombre, 'estado': True},
        )
        self.stdout.write(self.style.MIGRATE_HEADING('Medio de pago del cliente:'))
        self.stdout.write(f'  {medio.alias}: {"creado" if creado else "ya existía"}')

        self.stdout.write(self.style.SUCCESS(
            f'\nListo. {username} puede operar sobre "{principal.nombre}" '
            f'(comisión de {principal.get_preferencia_tipo_cambio_display()}, '
            f'límite de compra {principal.limite_compra}).'
        ))
