from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .backends import CustomOIDCBackend
from .models import Cliente, Usuario
from .oidc import provider_logout_url


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


class CustomOIDCBackendTests(TestCase):
    """E4-120: el backend OIDC sincroniza perfil, roles y acceso al admin
    desde los claims de Keycloak."""

    def setUp(self):
        self.backend = CustomOIDCBackend()

    def _user(self, **kw):
        defaults = dict(username='u1', email='u1@example.com')
        defaults.update(kw)
        return User.objects.create_user(**defaults)

    def test_sincroniza_perfil_basico(self):
        user = self._user()
        claims = {
            'given_name': 'Ana', 'family_name': 'García',
            'email': 'ana@example.com', 'preferred_username': 'ana',
        }
        self.backend._sync_user_profile(user, claims)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Ana')
        self.assertEqual(user.last_name, 'García')
        self.assertEqual(user.email, 'ana@example.com')
        self.assertEqual(user.username, 'ana')

    def test_roles_de_keycloak_se_reflejan_en_grupos(self):
        user = self._user()
        self.backend._sync_user_profile(user, {'roles': ['cajero', 'analista']})
        self.assertEqual(
            sorted(user.groups.values_list('name', flat=True)),
            ['analista', 'cajero'],
        )

    def test_rol_admin_otorga_acceso_al_panel(self):
        user = self._user()
        self.backend._sync_user_profile(user, {'roles': ['administrador']})
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_sin_rol_admin_no_hay_acceso_al_panel(self):
        user = self._user(is_staff=True, is_superuser=True)
        self.backend._sync_user_profile(user, {'roles': ['cajero']})
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_revocacion_de_rol_se_refleja(self):
        user = self._user()
        user.groups.add(Group.objects.create(name='cajero'))
        self.backend._sync_user_profile(user, {'roles': ['analista']})
        self.assertEqual(
            list(user.groups.values_list('name', flat=True)), ['analista']
        )

    def test_roles_internos_de_keycloak_se_ignoran(self):
        user = self._user()
        self.backend._sync_user_profile(user, {'roles': [
            'offline_access', 'uma_authorization',
            'default-roles-globalexchange', 'cajero',
        ]})
        self.assertEqual(
            list(user.groups.values_list('name', flat=True)), ['cajero']
        )

    def test_sin_claim_de_roles_no_toca_grupos(self):
        user = self._user()
        user.groups.add(Group.objects.create(name='manual'))
        self.backend._sync_user_profile(user, {'given_name': 'X'})
        self.assertEqual(
            list(user.groups.values_list('name', flat=True)), ['manual']
        )


class ProviderLogoutUrlTests(TestCase):
    """E4-120: la URL de logout apunta a Keycloak para cerrar la sesión SSO."""

    def setUp(self):
        self.rf = RequestFactory()

    def _request(self, session=None):
        req = self.rf.get('/')  # host por defecto: testserver
        req.session = session or {}
        return req

    def test_incluye_id_token_hint_si_esta_en_sesion(self):
        url = provider_logout_url(self._request({'oidc_id_token': 'TOKEN123'}))
        self.assertIn('protocol/openid-connect/logout', url)
        self.assertIn('id_token_hint=TOKEN123', url)
        self.assertIn('post_logout_redirect_uri=', url)

    def test_usa_client_id_si_no_hay_id_token(self):
        url = provider_logout_url(self._request())
        self.assertIn('client_id=django-backend', url)
        self.assertNotIn('id_token_hint', url)
