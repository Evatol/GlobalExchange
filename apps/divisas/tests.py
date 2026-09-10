from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Moneda, TasaCambio


class DivisasApiTests(APITestCase):

    def setUp(self):
        # Crear datos de prueba iniciales
        self.moneda_usd = Moneda.objects.create(
            codigo='USD',
            nombre='Dólar Estadounidense',
            simbolo='$',
            estado=True,
        )
        self.tasa_usd = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('7300.00'),
            tasa_venta=Decimal('7400.00'),
            origen='Banco Central',
            estado=True,
        )
        self.url_tasas = reverse('tasas-publicas')
        self.url_simular = reverse('simulador-conversion')

    def test_obtener_tasas_publicas(self):
        """Verifica que la consulta pública de tasas retorne un 200 OK y la lista de tasas."""
        response = self.client.get(self.url_tasas)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['moneda_codigo'], 'USD')

    def test_simulador_conversion_compra(self):
        """Verifica el cálculo correcto en una simulación de compra."""
        payload = {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'compra',
            'cantidad': '100.00',
        }
        response = self.client.post(self.url_simular, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 100 * 7300 = 730000.00
        self.assertEqual(Decimal(response.data['resultado']), Decimal('730000.00'))

    def test_simulador_conversion_venta(self):
        """Verifica el cálculo correcto en una simulación de venta."""
        payload = {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'venta',
            'cantidad': '100.00',
        }
        response = self.client.post(self.url_simular, payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 100 * 7400 = 740000.00
        self.assertEqual(Decimal(response.data['resultado']), Decimal('740000.00'))

    def test_simulador_moneda_no_encontrada(self):
        """Verifica que retorne un error 404 si la moneda no existe o no tiene tasa activa."""
        payload = {
            'moneda_codigo': 'EUR',
            'tipo_operacion': 'compra',
            'cantidad': '50.00',
        }
        response = self.client.post(self.url_simular, payload)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)