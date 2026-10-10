"""Simula a la pasarela de pago externa avisando por webhook (E4-158).

Sirve para probar y mostrar el flujo sin una pasarela real: arma el aviso, lo
firma con el mismo código que verifica el webhook (``apps.transacciones.webhook``)
y lo envía por HTTP al servidor en marcha.

Uso::

    python manage.py simular_webhook_pago PAS-1A2B3C...             # cobró
    python manage.py simular_webhook_pago PAS-1A2B3C... --rechazar  # no pudo cobrar
    python manage.py simular_webhook_pago PAS-1A2B3C... --firma-invalida
"""

import json
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from apps.transacciones import webhook


class Command(BaseCommand):
    help = 'Simula el aviso de la pasarela de pago externa al webhook (E4-158).'

    def add_arguments(self, parser):
        parser.add_argument('referencia', help='Referencia de la operación (PAS-...).')
        parser.add_argument(
            '--rechazar', action='store_true',
            help='Avisa que el cobro fue rechazado (la operación queda Fallida).',
        )
        parser.add_argument(
            '--firma-invalida', action='store_true',
            help='Envía una firma incorrecta: el webhook tiene que responder 403.',
        )
        parser.add_argument(
            '--url', default='http://localhost:8000',
            help='Servidor donde está el webhook (default: http://localhost:8000).',
        )

    def handle(self, *args, **options):
        cuerpo = json.dumps({
            'referencia': options['referencia'],
            'estado': 'RECHAZADO' if options['rechazar'] else 'PAGADO',
        }).encode()
        firma = 'firma-incorrecta' if options['firma_invalida'] else webhook.firmar(cuerpo)
        url = options['url'].rstrip('/') + '/api/transacciones/webhook/pago/'

        pedido = urllib.request.Request(
            url, data=cuerpo, method='POST',
            headers={'Content-Type': 'application/json', webhook.ENCABEZADO_FIRMA: firma},
        )
        try:
            with urllib.request.urlopen(pedido, timeout=10) as resp:
                codigo, respuesta = resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:  # 403, 404, 409...: también es una respuesta
            codigo, respuesta = exc.code, exc.read().decode()
        except urllib.error.URLError as exc:
            raise CommandError(f'No se pudo conectar con {url}: {exc.reason}')

        self.stdout.write(f'POST {url}\n-> {codigo} {respuesta}')
