from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import Cliente, Usuario


def cliente_valido(**overrides):
    datos = dict(
        nombre='Comercial Guaraní',
        documento='80012345-6',
        tipo='JURIDICA',
        razon_social='Comercial Guaraní S.A.',
        categoria=Cliente.CATEGORIA_CORPORATIVO,
        limite_compra=Decimal('1000000.00'),
        limite_venta=Decimal('500000.00'),
        preferencia_tipo_cambio=Cliente.PREFERENCIA_PREFERENCIAL,
    )
    datos.update(overrides)
    return datos


class ClienteModelTests(TestCase):
    """E4-124: pruebas del modelo Cliente (creación y validaciones)."""

    def test_creacion_basica_con_defaults(self):
        cliente = Cliente.objects.create(
            nombre='Juan Pérez',
            documento='1234567',
            tipo='FISICA',
        )
        self.assertEqual(cliente.categoria, Cliente.CATEGORIA_MINORISTA)
        self.assertEqual(
            cliente.preferencia_tipo_cambio, Cliente.PREFERENCIA_ESTANDAR
        )
        self.assertEqual(cliente.limite_compra, Decimal('0.00'))
        self.assertEqual(cliente.limite_venta, Decimal('0.00'))
        self.assertEqual(cliente.frecuencia_transacciones, 0)
        self.assertTrue(cliente.estado)
        self.assertIsNotNone(cliente.fecha_creacion)
        self.assertEqual(str(cliente), 'Juan Pérez')

    def test_documento_unico(self):
        Cliente.objects.create(**cliente_valido())
        with self.assertRaises(IntegrityError):
            Cliente.objects.create(**cliente_valido(nombre='Otro'))

    def test_clean_rechaza_limites_negativos(self):
        cliente = Cliente(**cliente_valido(limite_compra=Decimal('-1.00')))
        with self.assertRaises(ValidationError) as ctx:
            cliente.full_clean()
        self.assertIn('limite_compra', ctx.exception.message_dict)

    def test_clean_rechaza_frecuencia_negativa(self):
        cliente = Cliente(**cliente_valido(frecuencia_transacciones=-5))
        with self.assertRaises(ValidationError) as ctx:
            cliente.full_clean()
        self.assertIn('frecuencia_transacciones', ctx.exception.message_dict)

    def test_clean_exige_razon_social_para_juridica(self):
        cliente = Cliente(**cliente_valido(razon_social=''))
        with self.assertRaises(ValidationError) as ctx:
            cliente.full_clean()
        self.assertIn('razon_social', ctx.exception.message_dict)

    def test_clean_permite_fisica_sin_razon_social(self):
        cliente = Cliente(
            **cliente_valido(tipo='FISICA', razon_social='', nombre='Ana')
        )
        cliente.full_clean()  # no debe levantar

    def test_categoria_invalida_es_rechazada(self):
        cliente = Cliente(**cliente_valido(categoria='PLATINO'))
        with self.assertRaises(ValidationError):
            cliente.full_clean()

    def test_asociar_y_desasociar_usuario(self):
        cliente = Cliente.objects.create(**cliente_valido())
        usuario = Usuario.objects.create(
            username='operador1',
            email='operador1@example.com',
            nombres='Op',
            apellidos='Uno',
            telefono='0981000000',
            direccion='Asunción',
        )
        cliente.asociar_usuario(usuario)
        self.assertIn(usuario, cliente.usuarios.all())
        self.assertIn(cliente, usuario.clientes.all())
        cliente.desasociar_usuario(usuario)
        self.assertNotIn(usuario, cliente.usuarios.all())

    def test_helpers_de_segmentacion(self):
        cliente = Cliente.objects.create(**cliente_valido())
        cliente.actualizar_categoria(Cliente.CATEGORIA_VIP)
        cliente.establecer_limite_compra(Decimal('9.00'))
        cliente.establecer_limite_venta(Decimal('8.00'))
        cliente.establecer_frecuencia(3)
        cliente.refresh_from_db()
        self.assertEqual(cliente.categoria, Cliente.CATEGORIA_VIP)
        self.assertEqual(cliente.limite_compra, Decimal('9.00'))
        self.assertEqual(cliente.limite_venta, Decimal('8.00'))
        self.assertEqual(cliente.frecuencia_transacciones, 3)


class ClienteAPITests(TestCase):
    """E4-125: CRUD completo de Clientes sobre /api/usuarios/clientes/."""

    def setUp(self):
        self.client = APIClient()
        self.url = '/api/usuarios/clientes/'

    def test_crear_cliente(self):
        resp = self.client.post(self.url, cliente_valido(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(resp.data['categoria'], Cliente.CATEGORIA_CORPORATIVO)

    def test_crear_cliente_juridica_sin_razon_social_falla(self):
        resp = self.client.post(
            self.url, cliente_valido(razon_social=''), format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('razon_social', resp.data)

    def test_crear_cliente_limite_negativo_falla(self):
        resp = self.client.post(
            self.url, cliente_valido(limite_venta='-3.00'), format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('limite_venta', resp.data)

    def test_listar_clientes(self):
        Cliente.objects.create(**cliente_valido())
        Cliente.objects.create(
            **cliente_valido(nombre='Otra', documento='999', tipo='FISICA',
                             razon_social='')
        )
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['count'], 2)

    def test_filtrar_por_categoria(self):
        Cliente.objects.create(**cliente_valido())
        Cliente.objects.create(
            **cliente_valido(nombre='Mino', documento='111', tipo='FISICA',
                             razon_social='', categoria=Cliente.CATEGORIA_MINORISTA)
        )
        resp = self.client.get(self.url, {'categoria': Cliente.CATEGORIA_MINORISTA})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['nombre'], 'Mino')

    def test_ver_detalle(self):
        cliente = Cliente.objects.create(**cliente_valido())
        resp = self.client.get(f'{self.url}{cliente.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['documento'], '80012345-6')

    def test_editar_cliente(self):
        cliente = Cliente.objects.create(**cliente_valido())
        resp = self.client.patch(
            f'{self.url}{cliente.pk}/',
            {'categoria': Cliente.CATEGORIA_VIP, 'limite_compra': '2000000.00'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        cliente.refresh_from_db()
        self.assertEqual(cliente.categoria, Cliente.CATEGORIA_VIP)
        self.assertEqual(cliente.limite_compra, Decimal('2000000.00'))

    def test_eliminar_cliente(self):
        cliente = Cliente.objects.create(**cliente_valido())
        resp = self.client.delete(f'{self.url}{cliente.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Cliente.objects.count(), 0)

    def test_crear_cliente_con_usuarios_asociados(self):
        usuario = Usuario.objects.create(
            username='operador2',
            email='operador2@example.com',
            nombres='Op',
            apellidos='Dos',
            telefono='0981000001',
            direccion='Asunción',
        )
        payload = cliente_valido(usuarios=[usuario.pk])
        resp = self.client.post(self.url, payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        cliente = Cliente.objects.get(pk=resp.data['id'])
        self.assertIn(usuario, cliente.usuarios.all())
