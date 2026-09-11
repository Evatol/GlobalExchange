from decimal import Decimal
from django.test import TestCase
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


class CotizacionCRUDTests(APITestCase):
    """CRUD de cotizaciones (E4-26), implementado sobre TasaCambio."""

    def setUp(self):
        self.usd = Moneda.objects.create(
            codigo='USD', nombre='Dólar estadounidense', simbolo='$', estado=True
        )
        self.eur = Moneda.objects.create(
            codigo='EUR', nombre='Euro', simbolo='€', estado=True
        )
        self.cotizacion_usd = TasaCambio.objects.create(
            moneda=self.usd,
            tasa_compra=Decimal('7300.00'),
            tasa_venta=Decimal('7400.00'),
            origen='Banco Central',
            estado=True,
        )
        self.list_url = reverse('cotizacion-list')
        self.detail_url = reverse('cotizacion-detail', args=[self.cotizacion_usd.id])
        self.activar_url = reverse('cotizacion-activar', args=[self.cotizacion_usd.id])

    def test_listar_cotizaciones(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['moneda_codigo'], 'USD')

    def test_registrar_cotizacion(self):
        data = {
            'moneda': self.eur.id,
            'tasa_compra': '7900.00',
            'tasa_venta': '8000.00',
            'origen': 'Banco Central',
            'estado': True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TasaCambio.objects.filter(moneda=self.eur).count(), 1)

    def test_registrar_cotizacion_desactiva_la_anterior_de_la_misma_moneda(self):
        """Al crear una cotización nueva para USD, la anterior de USD queda inactiva
        (una sola cotización vigente por moneda, la que usan la vista pública y el
        simulador)."""
        data = {
            'moneda': self.usd.id,
            'tasa_compra': '7350.00',
            'tasa_venta': '7450.00',
            'origen': 'Banco Central',
            'estado': True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.cotizacion_usd.refresh_from_db()
        self.assertFalse(self.cotizacion_usd.estado)
        activas_usd = TasaCambio.objects.filter(moneda=self.usd, estado=True)
        self.assertEqual(activas_usd.count(), 1)
        self.assertEqual(activas_usd.first().tasa_venta, Decimal('7450.00'))

    def test_no_permite_tasa_venta_menor_a_tasa_compra(self):
        data = {
            'moneda': self.eur.id,
            'tasa_compra': '8000.00',
            'tasa_venta': '7900.00',
            'origen': 'Banco Central',
            'estado': True,
        }
        response = self.client.post(self.list_url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_editar_cotizacion(self):
        data = {
            'moneda': self.usd.id,
            'tasa_compra': '7320.00',
            'tasa_venta': '7420.00',
            'origen': 'Banco Central',
            'estado': True,
        }
        response = self.client.put(self.detail_url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cotizacion_usd.refresh_from_db()
        self.assertEqual(self.cotizacion_usd.tasa_venta, Decimal('7420.00'))

    def test_borrado_logico_desactiva_no_elimina(self):
        response = self.client.delete(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cotizacion_usd.refresh_from_db()
        self.assertFalse(self.cotizacion_usd.estado)
        self.assertTrue(TasaCambio.objects.filter(id=self.cotizacion_usd.id).exists())

    def test_activar_cotizacion(self):
        self.cotizacion_usd.estado = False
        self.cotizacion_usd.save()
        response = self.client.post(self.activar_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.cotizacion_usd.refresh_from_db()
        self.assertTrue(self.cotizacion_usd.estado)

    def test_filtrar_por_moneda(self):
        TasaCambio.objects.create(
            moneda=self.eur,
            tasa_compra=Decimal('7900.00'),
            tasa_venta=Decimal('8000.00'),
            origen='Banco Central',
            estado=True,
        )
        response = self.client.get(self.list_url, {'moneda': 'EUR'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['moneda_codigo'], 'EUR')

    def test_filtrar_por_estado(self):
        self.cotizacion_usd.estado = False
        self.cotizacion_usd.save()
        activas = self.client.get(self.list_url, {'estado': 'true'})
        inactivas = self.client.get(self.list_url, {'estado': 'false'})
        self.assertEqual(activas.data['count'], 0)
        self.assertEqual(inactivas.data['count'], 1)


class PantallaPublicaCambiosViewTests(TestCase):
    """Pantalla pública en HTML (cotizaciones del día + calculadora), visible
    sin haber iniciado sesión (RF13, RF20, RF24)."""

    def setUp(self):
        self.usd = Moneda.objects.create(
            codigo='USD', nombre='Dólar estadounidense', simbolo='$', estado=True
        )
        self.tasa_usd = TasaCambio.objects.create(
            moneda=self.usd,
            tasa_compra=Decimal('7300.00'),
            tasa_venta=Decimal('7400.00'),
            origen='Banco Central',
            estado=True,
        )
        self.url = reverse('pantalla-publica')

    def test_accesible_sin_login(self):
        """Un visitante anónimo puede ver la pantalla sin ser redirigido a un login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(response, 'divisas/publica.html')

    def test_muestra_las_tasas_activas(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'USD')
        self.assertContains(response, '7300')

    def test_login_apunta_a_keycloak_no_al_admin_de_django(self):
        """El link de login debe ir al flujo OIDC (Keycloak), no al admin de Django."""
        response = self.client.get(self.url)
        contenido = response.content.decode()
        self.assertIn(reverse('oidc_authentication_init'), contenido)
        self.assertNotIn(reverse('admin:login'), contenido)

    def test_calculadora_conversion_compra(self):
        response = self.client.post(self.url, {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'compra',
            'cantidad': '100.00',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.context['resultado'], Decimal('730000.00'))
        self.assertIsNone(response.context['error'])

    def test_calculadora_conversion_venta(self):
        response = self.client.post(self.url, {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'venta',
            'cantidad': '100.00',
        })
        self.assertEqual(response.context['resultado'], Decimal('740000.00'))

    def test_calculadora_moneda_sin_tasa_activa(self):
        response = self.client.post(self.url, {
            'moneda_codigo': 'EUR',
            'tipo_operacion': 'compra',
            'cantidad': '100.00',
        })
        self.assertIsNone(response.context['resultado'])
        self.assertIn('EUR', response.context['error'])

    def test_calculadora_cantidad_invalida_no_rompe_la_pagina(self):
        """Una cantidad no numérica no debe tirar un error 500: la vista debe
        mostrar un mensaje de validación, igual que hace el simulador por API."""
        response = self.client.post(self.url, {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'compra',
            'cantidad': 'no-es-un-numero',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.context['resultado'])
        self.assertIsNotNone(response.context['error'])

    def test_calculadora_usa_la_misma_tasa_que_el_simulador_por_api(self):
        """La pantalla pública y /api/divisas/simular/ deben calcular igual:
        comparten la misma consulta (TasaCambio.objects.activa_para)."""
        respuesta_html = self.client.post(self.url, {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'venta',
            'cantidad': '50.00',
        })
        respuesta_api = self.client.post(reverse('simulador-conversion'), {
            'moneda_codigo': 'USD',
            'tipo_operacion': 'venta',
            'cantidad': '50.00',
        })
        self.assertEqual(
            respuesta_html.context['resultado'],
            Decimal(respuesta_api.data['resultado']),
        )
