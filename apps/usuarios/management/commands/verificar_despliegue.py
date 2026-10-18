"""Comprobación funcional posterior al despliegue (smoke test).

Verifica desde adentro de la aplicación lo que ``scripts/verificar_produccion.sh``
no puede ver desde afuera, porque las pantallas piden iniciar sesión: que la
base de datos responda, que las pantallas de facturación y de caja funcionen,
que se pueda generar el PDF de una factura emitida y que cada terminal de
autoservicio tenga su caja abierta con billetes.

Imprime una línea por comprobación, ``OK ...`` o ``FALLA ...``, y termina con
código 1 si alguna falló, para que el script que lo invoca lo reporte. Cuando
algo falla, ``docs/produccion.md`` explica cómo resolverlo.

No deja rastros: usa un usuario administrador temporal y todo corre dentro de
una transacción que se revierte al final.

Uso::

    python manage.py verificar_despliegue
    python manage.py verificar_despliegue --sin-datos
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client
from django.urls import reverse

from apps.caja.models import Caja, StockBillete
from apps.facturacion.models import Factura
from apps.usuarios.management.commands.seed_datos_demo import TERMINALES


class Falla(Exception):
    """Una comprobación que no se cumplió (el mensaje explica por qué)."""


class Command(BaseCommand):
    help = (
        'Comprueba que la base, las pantallas de facturación y de caja, el PDF '
        'de una factura y las terminales funcionan. Falla con código 1 si algo no.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sin-datos',
            action='store_true',
            help='No exige datos de demostración (facturas emitidas, PDF ni cajas '
                 'abiertas): solo comprueba que las pantallas respondan.',
        )

    def handle(self, *args, **options):
        exige_datos = not options['sin_datos']
        resultados = []

        def comprobar(nombre, funcion):
            # Cada comprobación corre en su propio savepoint: un error de base
            # de datos en una no deja inutilizables a las que siguen.
            try:
                with transaction.atomic():
                    detalle = funcion()
            except Falla as exc:
                resultados.append((False, f'{nombre}: {exc}'))
            except Exception as exc:  # cualquier otro error también es una falla
                resultados.append((False, f'{nombre}: {type(exc).__name__}: {exc}'))
            else:
                resultados.append((True, f'{nombre}: {detalle}'))

        with transaction.atomic():
            admin = get_user_model().objects.create_superuser(
                'smoke_test', 'smoke_test@example.com', 'x'
            )
            cliente = Client(HTTP_HOST=_host_permitido())
            cliente.force_login(admin)

            def pantalla(url_nombre, args=None, aceptar=(200,)):
                respuesta = cliente.get(reverse(url_nombre, args=args), secure=True)
                if respuesta.status_code not in aceptar:
                    raise Falla(f'respondió {respuesta.status_code} y se esperaba {aceptar[0]}')
                return respuesta

            def base_de_datos():
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                return 'responde a consultas'

            def listado_de_facturas():
                pantalla('lista_facturas')
                return 'el listado responde'

            def facturas_emitidas():
                cantidad = Factura.objects.filter(estado=Factura.ESTADO_EMITIDA).count()
                if cantidad == 0:
                    raise Falla('no hay facturas emitidas (falta correr seed_datos_demo)')
                return f'{cantidad} facturas emitidas'

            def pdf_de_una_factura():
                factura = Factura.objects.filter(estado=Factura.ESTADO_EMITIDA).first()
                if factura is None:
                    raise Falla('no hay una factura emitida para generar el PDF')
                respuesta = pantalla('descargar_factura_pdf', args=[factura.pk])
                if not respuesta.content.startswith(b'%PDF'):
                    raise Falla('la descarga no devolvió un PDF')
                return f'PDF de la factura #{factura.pk} generado ({len(respuesta.content)} bytes)'

            def pantallas_de_caja():
                pantalla('gestion_sucursales')
                pantalla('gestion_cajas')
                return 'sucursales y cajas responden'

            def terminales():
                sin_billetes = []
                for nombre, _direccion, _usuario in TERMINALES:
                    caja = Caja.objects.filter(sucursal__nombre=nombre, estado='ABIERTA').first()
                    if caja is None or not StockBillete.objects.filter(
                        caja=caja, cantidad__gt=0
                    ).exists():
                        sin_billetes.append(nombre)
                if sin_billetes:
                    raise Falla(
                        'sin caja abierta con billetes: ' + ', '.join(sin_billetes)
                        + ' (falta correr seed_datos_demo)'
                    )
                return f'{len(TERMINALES)} terminal(es) con su caja abierta y billetes'

            comprobar('Base de datos', base_de_datos)
            comprobar('Facturación, listado', listado_de_facturas)
            comprobar('Caja', pantallas_de_caja)
            if exige_datos:
                comprobar('Facturación, datos', facturas_emitidas)
                comprobar('Facturación, PDF', pdf_de_una_factura)
                comprobar('Terminal, stock', terminales)

            # No deja rastros: ni el usuario temporal ni su sesión.
            transaction.set_rollback(True)

        fallas = 0
        for correcta, texto in resultados:
            self.stdout.write(f'{"OK" if correcta else "FALLA"} {texto}')
            fallas += 0 if correcta else 1
        if fallas:
            raise CommandError(f'{fallas} comprobación(es) fallaron.')


def _host_permitido():
    """Un host de ``ALLOWED_HOSTS`` con el que el cliente de prueba pueda
    hacer los pedidos (``localhost`` si no hay uno concreto)."""
    for host in settings.ALLOWED_HOSTS:
        if host and host != '*' and not host.startswith('.'):
            return host
    return 'localhost'