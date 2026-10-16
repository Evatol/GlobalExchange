from django.core.management.base import BaseCommand

from apps.facturacion.models import Factura
from apps.transacciones.models import Transaccion


class Command(BaseCommand):
    help = 'Emite una factura para cada transacción exitosa que todavía no tiene (datos de demo).'

    def handle(self, *args, **options):
        pendientes = Transaccion.objects.filter(estado='EXITOSA', factura__isnull=True)
        creadas = 0
        for transaccion in pendientes:
            Factura(transaccion=transaccion).generar()
            creadas += 1
        self.stdout.write(self.style.SUCCESS(f'Facturas emitidas: {creadas}'))