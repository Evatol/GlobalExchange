from django.test import TestCase

# Create your tests here. 
from decimal import Decimal
from django.contrib.auth.models import User as DjangoUser
from django.test import TestCase
from django.urls import reverse
from apps.divisas.models import Moneda, TasaCambio
from apps.divisas.services import procesar_cambio_cotizacion
from apps.notificaciones.models import Notificaciones
from apps.usuarios.models import Usuario


class NotificacionesVariacionPrecioTests(TestCase): #E4-32
    def setUp(self):
        # Crear monedas
        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólar', estado=True)
        self.moneda_eur = Moneda.objects.create(codigo='EUR', nombre='Euro', estado=True)

        # Crear usuarios
        self.user_con_favorita = Usuario.objects.create(
            username='romina',
            email='romina@example.com',
            nombres='Romina',
            apellidos='Test',
            telefono='000000000',
            direccion='Dirección de prueba',
        )
        self.user_con_favorita.monedas_favoritas.add(self.moneda_usd)

        self.user_sin_favorita = Usuario.objects.create(
            username='visitante',
            email='visitante@example.com',
            nombres='Visitante',
            apellidos='Test',
            telefono='000000001',
            direccion='Dirección de prueba',
        )

    def test_variacion_menor_o_igual_a_uno_por_ciento_no_genera_aviso(self,):
        # Cotización inicial
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.00'),
            tasa_venta=Decimal('105.00'),
            estado=True
        )
        # Cotización nueva con un cambio del 0.5% (menor al umbral de 1.0%)
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.50'),
            tasa_venta=Decimal('105.50'),
            estado=True
        )

        procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # No debe crearse ninguna notificación
        self.assertEqual(Notificaciones.objects.count(), 0)

    def test_variacion_mayor_a_uno_por_ciento_genera_aviso_para_favoritos(self):
        # Cotización inicial
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('100.00'),
            tasa_venta=Decimal('105.00'),
            estado=True
        )
        # Cotización nueva con un cambio mayor al 1% (ej. 3%)
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_usd,
            tasa_compra=Decimal('103.00'),
            tasa_venta=Decimal('108.00'),
            estado=True
        )

        procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # Debe crearse una notificación únicamente para el usuario con la moneda en favorita
        notificaciones = Notificaciones.objects.all()
        self.assertEqual(notificaciones.count(), 1)
        self.assertEqual(notificaciones[0].usuario, self.user_con_favorita)
        self.assertIn('USD', notificaciones[0].titulo)

    def test_endpoint_consultar_notificaciones_nuevas(self):
        # Crear una notificación directa para romina
        Notificaciones.objects.create(
            usuario=self.user_con_favorita,
            titulo='Variación Relevante: USD',
            mensaje='La cotización ha variado.',
            tipo='variacion_cotizacion',
            leida=False
        )

        # Autenticar como romina y consultar la API
        DjangoUser.objects.create_user(username='romina', password='password123')
        self.client.login(username='romina', password='password123')
        url = reverse('api_notificaciones_nuevas')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['notificaciones']), 1)
        self.assertEqual(data['notificaciones'][0]['titulo'], 'Variación Relevante: USD')

    def test_usuario_sin_favorita_no_ve_ni_recibe_avisos(self):
        # Cotización con gran variación
        tasa_ant = TasaCambio.objects.create(
            moneda=self.moneda_eur,
            tasa_compra=Decimal('500.00'),
            tasa_venta=Decimal('510.00'),
            estado=True
        )
        tasa_nueva = TasaCambio.objects.create(
            moneda=self.moneda_eur,
            tasa_compra=Decimal('550.00'),
            tasa_venta=Decimal('560.00'),
            estado=True
        )

        procesar_cambio_cotizacion(tasa_nueva, tasa_ant)

        # Ningún usuario tiene EUR como favorita, no debe haber notificacioneses
        self.assertEqual(Notificaciones.objects.count(), 0)