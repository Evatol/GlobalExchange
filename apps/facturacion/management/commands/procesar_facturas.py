"""``manage.py procesar_facturas``: pone al día las facturas electrónicas.

Crea la factura de las operaciones exitosas que no la tengan, reintenta las que no se
pudieron enviar (cuando ya llegó su hora de reintento) y consulta a SIFEN las enviadas
hasta que queden emitidas o rechazadas, y reenvía los correos de factura que no salieron.
Pensado para correr cada pocos minutos (cron).
"""

from django.core.management.base import BaseCommand

from apps.facturacion.models import Factura
from apps.facturacion.services import procesar_pendientes


class Command(BaseCommand):
    help = 'Crea, reintenta y consulta las facturas electrónicas pendientes.'

    def handle(self, *args, **options):
        resumen = procesar_pendientes()
        self.stdout.write(
            f"Facturas creadas: {resumen['registradas']} | enviadas: {resumen['enviadas']} "
            f"| consultadas a SIFEN: {resumen['consultadas']} "
            f"| correos reenviados: {resumen['correos']}"
        )
        for estado, etiqueta in Factura.ESTADOS:
            self.stdout.write(f'  {etiqueta}: {Factura.objects.filter(estado=estado).count()}')
