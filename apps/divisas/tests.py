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
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Moneda


class MonedaCRUDTests(APITestCase):

    def setUp(self):
        self.moneda = Moneda.objects.create(
            codigo='USD',
            nombre='Dólar estadounidense',
            simbolo='$',
            estado=True
        )
        self.list_url = reverse('moneda-list')
        self.detail_url = reverse('moneda-detail', args=[self.moneda.id])
        self.activar_url = reverse('moneda-activar', args=[self.moneda.id])

    def test_listar_monedas(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_registrar_moneda(self):
        data = {
            'codigo': 'EUR',
            'nombre': 'Euro',
            'simbolo': '€',
            'estado': True
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Moneda.objects.count(), 2)
        self.assertEqual(response.data['codigo'], 'EUR')

    def test_no_permite_codigo_duplicado(self):
        data = {
            'codigo': 'USD',
            'nombre': 'Otro dólar',
            'simbolo': '$',
            'estado': True
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_editar_moneda(self):
        data = {
            'codigo': 'USD',
            'nombre': 'Dólar de Estados Unidos',
            'simbolo': '$',
            'estado': True
        }
        response = self.client.put(self.detail_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.moneda.refresh_from_db()
        self.assertEqual(self.moneda.nombre, 'Dólar de Estados Unidos')

    def test_borrado_logico_desactiva_no_elimina(self):
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.moneda.refresh_from_db()
        self.assertFalse(self.moneda.estado)
        # Confirma que el registro sigue existiendo en la base
        self.assertTrue(Moneda.objects.filter(id=self.moneda.id).exists())

    def test_activar_moneda(self):
        self.moneda.estado = False
        self.moneda.save()
        response = self.client.post(self.activar_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.moneda.refresh_from_db()
        self.assertTrue(self.moneda.estado)

    def test_filtrar_por_codigo(self):
        Moneda.objects.create(codigo='EUR', nombre='Euro', simbolo='€')
        response = self.client.get(self.list_url, {'codigo': 'EUR'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['codigo'], 'EUR')

    def test_filtrar_por_estado(self):
        Moneda.objects.create(codigo='EUR', nombre='Euro', simbolo='€', estado=False)
        activas = self.client.get(self.list_url, {'estado': 'true'})
        inactivas = self.client.get(self.list_url, {'estado': 'false'})
        self.assertEqual(activas.data['count'], 1)
        self.assertEqual(inactivas.data['count'], 1)
        self.assertEqual(inactivas.data['results'][0]['codigo'], 'EUR')
