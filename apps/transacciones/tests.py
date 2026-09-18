"""from django.test import TestCase

# Create your tests here."""

# caso de prueba para validar que la transaccion se cancele automaticamente si la tasa de cambio sufre modificaciones
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.usuarios.models import Usuario, Cliente
from apps.divisas.models import Moneda, TasaCambio
from apps.transacciones.models import MetodoPago, Transaccion

class TransaccionTasaCambioTestCase(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create(
            username="testuser",
            email="test@mail.com",
            nombres="Test",
            apellidos="User",
            telefono="0981123456",
            direccion="Asunción"
        )
        self.cliente = Cliente.objects.create(
            nombre="Test Client",
            documento="123456",
            tipo="FISICA"
        )
        self.moneda = Moneda.objects.create(
            codigo="USD",
            nombre="Dólar",
            simbolo="$",
            estado=True
        )
        # Creamos la tasa inicial asociada a la moneda
        self.tasa_cambio_obj = TasaCambio.objects.create(
            moneda=self.moneda,
            tasa_compra=Decimal('7300.00'),
            tasa_venta=Decimal('7400.00'),
            origen="Banco Central",
            estado=True
        )
        self.metodo_pago = MetodoPago.objects.create(
            nombre="Efectivo",
            tipo="Físico",
            estado=True
        )

    def test_cancelar_transaccion_si_cambia_tasa(self):
        transaccion = Transaccion.objects.create(
            usuario=self.usuario,
            cliente=self.cliente,
            moneda=self.moneda,
            metodo_pago=self.metodo_pago,
            tipo='COMPRA',
            cantidad=Decimal('10.00'),
            tasa_cambio=Decimal('7300.00'),
            modalidad='Efectivo'
        )

        # Simulamos que la tasa de compra cambia antes de confirmar
        self.tasa_cambio_obj.tasa_compra = Decimal('7450.00')
        self.tasa_cambio_obj.save()

        # Al intentar confirmar, debe lanzar ValidationError y marcarse como CANCELADA
        with self.assertRaises(ValidationError):
            transaccion.confirmar()

        transaccion.refresh_from_db()
        self.assertEqual(transaccion.estado, 'CANCELADA')