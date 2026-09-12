from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from rest_framework import status
from rest_framework.test import APIClient

from . import services as services_module
from .backends import CustomOIDCBackend
from .models import Cliente, Usuario
from .oidc import provider_logout_url
from .services import enviar_credenciales_por_correo


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


class AsignacionUsuariosClientesTests(TestCase):
    """RF42: endpoints dedicados de asignación usuario <-> cliente."""

    def setUp(self):
        self.client = APIClient()
        self.cliente = Cliente.objects.create(**cliente_valido())
        self.usuario = Usuario.objects.create(
            username='op1', email='op1@example.com', nombres='Op', apellidos='Uno',
            telefono='0981000000', direccion='Asunción',
        )
        self.base = f'/api/usuarios/clientes/{self.cliente.pk}/'

    def test_asignar_usuario(self):
        r = self.client.post(
            f'{self.base}asignar-usuario/', {'usuario': self.usuario.pk}, format='json'
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertIn(self.usuario, self.cliente.usuarios.all())
        self.assertIn(self.usuario.pk, r.data['usuarios'])

    def test_asignar_usuario_inexistente_falla(self):
        r = self.client.post(
            f'{self.base}asignar-usuario/', {'usuario': 99999}, format='json'
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_asignar_sin_campo_usuario_falla(self):
        r = self.client.post(f'{self.base}asignar-usuario/', {}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_asignar_es_idempotente(self):
        for _ in range(2):
            r = self.client.post(
                f'{self.base}asignar-usuario/', {'usuario': self.usuario.pk}, format='json'
            )
            self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(self.cliente.usuarios.count(), 1)

    def test_desasignar_usuario(self):
        self.cliente.asociar_usuario(self.usuario)
        r = self.client.post(
            f'{self.base}desasignar-usuario/', {'usuario': self.usuario.pk}, format='json'
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.usuario, self.cliente.usuarios.all())

    def test_listar_usuarios_asignados(self):
        self.cliente.asociar_usuario(self.usuario)
        r = self.client.get(f'{self.base}usuarios/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['username'], 'op1')


class AltaUsuarioPorAdminTests(TestCase):
    """RF1-RF3: alta de usuario por el administrador (crear_usuario_keycloak)."""

    def test_enviar_credenciales_por_correo(self):
        enviar_credenciales_por_correo('nuevo@example.com', 'nuevo', 'Secreta-123!')
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['nuevo@example.com'])
        self.assertIn('Secreta-123!', msg.body)
        self.assertIn('nuevo', msg.body)

    @patch('apps.usuarios.services.create_user_in_keycloak')
    def test_comando_crea_en_keycloak_y_envia_correo(self, mock_create):
        mock_create.return_value = {
            'user_id': 'abc-123', 'username': 'jperez', 'email': 'jperez@example.com',
            'role': 'cajero', 'generated_password': 'Rnd-Pass-9!',
        }
        call_command(
            'crear_usuario_keycloak', 'jperez', 'jperez@example.com',
            '--rol', 'cajero', '--nombre', 'Juan', stdout=StringIO(),
        )
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs['username'], 'jperez')
        self.assertEqual(kwargs['role_name'], 'cajero')
        self.assertEqual(kwargs['first_name'], 'Juan')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Rnd-Pass-9!', mail.outbox[0].body)

    @patch('apps.usuarios.services.create_user_in_keycloak')
    def test_comando_no_email_no_envia(self, mock_create):
        mock_create.return_value = {
            'user_id': 'x', 'username': 'u', 'email': 'u@example.com',
            'role': 'cajero', 'generated_password': 'p',
        }
        call_command(
            'crear_usuario_keycloak', 'u', 'u@example.com', '--no-email',
            stdout=StringIO(),
        )
        self.assertEqual(len(mail.outbox), 0)


class PuenteUsuarioNegocioTests(TestCase):
    """RF43: el backend OIDC crea un Usuario (negocio) espejando al User de auth."""

    def setUp(self):
        self.backend = CustomOIDCBackend()

    def test_sync_crea_usuario_negocio(self):
        user = User.objects.create_user('jperez', 'jperez@example.com')
        self.backend._sync_user_profile(user, {
            'given_name': 'Juan', 'family_name': 'Pérez',
            'email': 'jperez@example.com', 'preferred_username': 'jperez',
        })
        usuario = Usuario.objects.get(username='jperez')
        self.assertEqual(usuario.email, 'jperez@example.com')
        self.assertEqual(usuario.nombres, 'Juan')

    def test_sync_no_pisa_telefono_ni_direccion(self):
        Usuario.objects.create(
            username='ana', email='ana@example.com', nombres='Ana', apellidos='G',
            telefono='0981123456', direccion='Asunción',
        )
        user = User.objects.create_user('ana', 'ana@example.com')
        self.backend._sync_user_profile(user, {
            'given_name': 'Ana María', 'family_name': 'González',
            'email': 'ana@example.com', 'preferred_username': 'ana',
        })
        usuario = Usuario.objects.get(username='ana')
        self.assertEqual(usuario.nombres, 'Ana María')
        self.assertEqual(usuario.telefono, '0981123456')
        self.assertEqual(usuario.direccion, 'Asunción')


class SelectorClienteActivoTests(TestCase):
    """RF43: selección del cliente activo en la sesión."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user('op', 'op@example.com')
        self.usuario = Usuario.objects.create(
            username='op', email='op@example.com', nombres='Op', apellidos='Uno',
        )
        self.c1 = Cliente.objects.create(nombre='Cliente Uno', documento='C1', tipo='FISICA')
        self.c2 = Cliente.objects.create(nombre='Cliente Dos', documento='C2', tipo='FISICA')
        self.inactivo = Cliente.objects.create(
            nombre='Inactivo', documento='C3', tipo='FISICA', estado=False,
        )
        self.usuario.clientes.add(self.c1, self.c2, self.inactivo)
        self.client.force_authenticate(user=self.user)

    def test_mis_clientes_lista_solo_activos_asociados(self):
        resp = self.client.get('/api/usuarios/mis-clientes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        nombres = {c['nombre'] for c in resp.data['clientes']}
        self.assertEqual(nombres, {'Cliente Uno', 'Cliente Dos'})

    def test_seleccionar_cliente_activo(self):
        resp = self.client.post('/api/usuarios/cliente-activo/', {'cliente': self.c2.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['nombre'], 'Cliente Dos')
        # persiste en la sesión
        self.assertEqual(self.client.get('/api/usuarios/cliente-activo/').data['id'], self.c2.pk)

    def test_no_puede_elegir_cliente_no_asociado(self):
        ajeno = Cliente.objects.create(nombre='Ajeno', documento='C9', tipo='FISICA')
        resp = self.client.post('/api/usuarios/cliente-activo/', {'cliente': ajeno.pk}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_auto_selecciona_si_hay_uno_solo(self):
        self.usuario.clientes.set([self.c1])
        resp = self.client.get('/api/usuarios/cliente-activo/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], self.c1.pk)

    def test_sin_cliente_activo_devuelve_404(self):
        resp = self.client.get('/api/usuarios/cliente-activo/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_formulario_del_menu_cambia_el_cliente(self):
        self.client.force_login(self.user)
        self.client.post('/api/usuarios/seleccionar-cliente/', {'cliente': self.c2.pk})
        resp = self.client.get('/api/usuarios/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.context['cliente_activo'], self.c2)

    def test_endpoints_requieren_login(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(
            self.client.get('/api/usuarios/mis-clientes/').status_code,
            status.HTTP_403_FORBIDDEN,
        )


class GestionRolesTests(TestCase):
    """RF46/RF48: pantalla de administración de roles (solo para el rol
    'administrador', reflejado como is_staff por CustomOIDCBackend)."""

    def setUp(self):
        self.admin = User.objects.create_user('admin_demo', 'admin@example.com', is_staff=True)
        self.no_admin = User.objects.create_user('cliente_demo', 'cliente@example.com')

    @patch('apps.usuarios.services.listar_usuarios_con_roles')
    def test_accesible_para_administrador(self, mock_listar):
        mock_listar.return_value = [
            {'id': '1', 'username': 'analista_demo', 'email': 'a@example.com', 'rol': 'analista'},
        ]
        self.client.force_login(self.admin)
        resp = self.client.get('/api/usuarios/roles/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'usuarios/gestion_roles.html')
        self.assertEqual(resp.context['usuarios'][0]['username'], 'analista_demo')

    def test_prohibido_para_no_administrador(self):
        self.client.force_login(self.no_admin)
        resp = self.client.get('/api/usuarios/roles/')
        self.assertEqual(resp.status_code, 403)

    def test_requiere_login(self):
        resp = self.client.get('/api/usuarios/roles/')
        self.assertEqual(resp.status_code, 302)  # redirige al login

    @patch('apps.usuarios.services.asignar_rol_negocio')
    def test_asignar_rol_llama_al_servicio(self, mock_asignar):
        self.client.force_login(self.admin)
        resp = self.client.post('/api/usuarios/roles/asignar/', {
            'username': 'analista_demo', 'rol': 'analista',
        })
        self.assertRedirects(resp, '/api/usuarios/roles/')
        mock_asignar.assert_called_once_with('analista_demo', 'analista')

    @patch('apps.usuarios.services.asignar_rol_negocio')
    def test_asignar_rol_ignora_rol_invalido(self, mock_asignar):
        self.client.force_login(self.admin)
        self.client.post('/api/usuarios/roles/asignar/', {
            'username': 'analista_demo', 'rol': 'super-hacker',
        })
        mock_asignar.assert_not_called()

    @patch('apps.usuarios.services.asignar_rol_negocio')
    def test_asignar_rol_prohibido_para_no_administrador(self, mock_asignar):
        self.client.force_login(self.no_admin)
        resp = self.client.post('/api/usuarios/roles/asignar/', {
            'username': 'analista_demo', 'rol': 'analista',
        })
        self.assertEqual(resp.status_code, 403)
        mock_asignar.assert_not_called()


class AsignarRolNegocioServiceTests(TestCase):
    """Pruebas unitarias de la lógica de apps.usuarios.services.asignar_rol_negocio
    y listar_usuarios_con_roles, contra un KeycloakAdmin simulado."""

    def test_rol_invalido_lanza_value_error(self):
        with self.assertRaises(ValueError):
            services_module.asignar_rol_negocio('quien-sea', 'no-existe')

    @patch('apps.usuarios.services._keycloak_admin')
    def test_usuario_inexistente_lanza_value_error(self, mock_admin_factory):
        mock_admin = mock_admin_factory.return_value
        mock_admin.get_user_id.return_value = None
        with self.assertRaises(ValueError):
            services_module.asignar_rol_negocio('fantasma', 'analista')

    @patch('apps.usuarios.services._keycloak_admin')
    def test_quita_el_rol_anterior_y_asigna_el_nuevo(self, mock_admin_factory):
        mock_admin = mock_admin_factory.return_value
        mock_admin.get_user_id.return_value = 'uid-1'
        mock_admin.get_realm_roles_of_user.return_value = [
            {'name': 'analista', 'id': 'r-analista'},
            {'name': 'default-roles-globalexchange', 'id': 'r-default'},
        ]
        mock_admin.get_realm_role.return_value = {'name': 'administrador', 'id': 'r-admin'}

        resultado = services_module.asignar_rol_negocio('juan', 'administrador')

        self.assertEqual(resultado, 'administrador')
        mock_admin.delete_realm_roles_of_user.assert_called_once_with(
            user_id='uid-1', roles=[{'name': 'analista', 'id': 'r-analista'}],
        )
        mock_admin.assign_realm_roles.assert_called_once_with(
            user_id='uid-1', roles=[{'name': 'administrador', 'id': 'r-admin'}],
        )

    @patch('apps.usuarios.services._keycloak_admin')
    def test_no_reasigna_si_ya_tiene_ese_rol(self, mock_admin_factory):
        mock_admin = mock_admin_factory.return_value
        mock_admin.get_user_id.return_value = 'uid-1'
        mock_admin.get_realm_roles_of_user.return_value = [
            {'name': 'analista', 'id': 'r-analista'},
        ]

        services_module.asignar_rol_negocio('juan', 'analista')

        mock_admin.delete_realm_roles_of_user.assert_not_called()
        mock_admin.assign_realm_roles.assert_not_called()

    @patch('apps.usuarios.services._keycloak_admin')
    def test_listar_usuarios_con_roles_detecta_el_rol_de_negocio(self, mock_admin_factory):
        mock_admin = mock_admin_factory.return_value
        mock_admin.get_users.return_value = [
            {'id': 'uid-1', 'username': 'juan', 'email': 'juan@example.com'},
            {'id': 'uid-2', 'username': 'ana', 'email': 'ana@example.com'},
        ]
        mock_admin.get_realm_roles_of_user.side_effect = [
            [{'name': 'default-roles-globalexchange'}, {'name': 'administrador'}],
            [{'name': 'offline_access'}],  # sin rol de negocio todavia
        ]

        usuarios = services_module.listar_usuarios_con_roles()

        por_username = {u['username']: u['rol'] for u in usuarios}
        self.assertEqual(por_username['juan'], 'administrador')
        self.assertIsNone(por_username['ana'])
