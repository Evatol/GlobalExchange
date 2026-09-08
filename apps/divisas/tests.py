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