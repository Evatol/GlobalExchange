from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from apps.usuarios.models import Cliente, Usuario
from .models import MedioPagoCliente, MetodoPago


def _cliente(**kw):
    datos = dict(nombre='Comercial Guaraní', documento='80012345-6', tipo='FISICA')
    datos.update(kw)
    return Cliente.objects.create(**datos)


def _usuario_con_rol(username, rol=None, **kwargs):
    """Usuario de Django con un rol de negocio (grupo), para probar permisos
    sin depender de un login real por Keycloak."""
    user = User.objects.create_user(username, **kwargs)
    if rol:
        grupo, _ = Group.objects.get_or_create(name=rol)
        user.groups.add(grupo)
    return user


class MetodoPagoCRUDTests(APITestCase):
    """RF102: catálogo de métodos de pago."""

    def setUp(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_metodo', rol='administrador'))
        self.url = '/api/transacciones/metodos-pago/'
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='BANCO')

    def test_crear_y_listar(self):
        resp = self.client.post(
            self.url, {'nombre': 'Billetera', 'tipo': 'WALLET'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.client.get(self.url).data['count'], 2)

    def test_borrado_logico(self):
        resp = self.client.delete(f'{self.url}{self.metodo.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.metodo.refresh_from_db()
        self.assertFalse(self.metodo.estado)
        self.assertTrue(MetodoPago.objects.filter(pk=self.metodo.pk).exists())

    def test_filtrar_por_tipo(self):
        MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        resp = self.client.get(self.url, {'tipo': 'CASH'})
        self.assertEqual(resp.data['count'], 1)


class MedioPagoClienteCRUDTests(APITestCase):
    """RF17: medios de pago de un cliente."""

    def setUp(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_mediopago', rol='administrador'))
        self.url = '/api/transacciones/medios-pago-cliente/'
        self.cliente = _cliente()
        self.otro_cliente = _cliente(nombre='Otro', documento='999')
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='BANCO')
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente,
            metodo_pago=self.metodo,
            alias='Cuenta Itaú',
            identificador='0123456789',
        )

    def _payload(self, **kw):
        datos = dict(
            cliente=self.cliente.pk,
            metodo_pago=self.metodo.pk,
            alias='Tigo Money',
            identificador='0981111222',
        )
        datos.update(kw)
        return datos

    def test_crear_medio_de_pago(self):
        resp = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.cliente.medios_pago.count(), 2)
        self.assertEqual(resp.data['metodo_pago_nombre'], 'Transferencia')

    def test_no_permite_duplicado_mismo_cliente(self):
        resp = self.client.post(
            self.url, self._payload(alias='Otra', identificador='0123456789'),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mismo_identificador_otro_cliente_si_permite(self):
        resp = self.client.post(
            self.url,
            self._payload(cliente=self.otro_cliente.pk, identificador='0123456789'),
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_rechaza_metodo_de_pago_desactivado(self):
        self.metodo.desactivar()
        resp = self.client.post(self.url, self._payload(), format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('metodo_pago', resp.data)

    def test_filtrar_por_cliente(self):
        MedioPagoCliente.objects.create(
            cliente=self.otro_cliente, metodo_pago=self.metodo,
            alias='x', identificador='y',
        )
        resp = self.client.get(self.url, {'cliente': self.cliente.pk})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['alias'], 'Cuenta Itaú')

    def test_borrado_logico(self):
        resp = self.client.delete(f'{self.url}{self.medio.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.medio.refresh_from_db()
        self.assertFalse(self.medio.estado)
        self.assertTrue(MedioPagoCliente.objects.filter(pk=self.medio.pk).exists())

    def test_activar(self):
        self.medio.desactivar()
        resp = self.client.post(f'{self.url}{self.medio.pk}/activar/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.medio.refresh_from_db()
        self.assertTrue(self.medio.estado)


class PermisosMetodoPagoTests(APITestCase):
    """Catálogo de métodos de pago: lectura libre, solo administrador escribe."""

    def setUp(self):
        self.url = '/api/transacciones/metodos-pago/'
        self.payload = {'nombre': 'Cheque', 'tipo': 'CHEQUE'}

    def test_lectura_libre(self):
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    def test_analista_no_puede_crear(self):
        self.client.force_authenticate(user=_usuario_con_rol('analista_mp', rol='analista'))
        resp = self.client.post(self.url, self.payload)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_administrador_puede_crear(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_mp', rol='administrador'))
        resp = self.client.post(self.url, self.payload)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)


class PermisosMedioPagoClienteTests(APITestCase):
    """RF17/RF43: usuario_final solo ve/gestiona los medios de pago del
    cliente activo de su sesión; administrador ve todos."""

    def setUp(self):
        from apps.usuarios.sesion import SESSION_KEY
        self.SESSION_KEY = SESSION_KEY

        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.cliente_propio = _cliente(nombre='Cliente Propio', documento='P1')
        self.cliente_ajeno = _cliente(nombre='Cliente Ajeno', documento='A1')

        self.user_final = _usuario_con_rol('final_x', rol='usuario_final')
        usuario_negocio = Usuario.objects.create(
            username='final_x', email='final_x@example.com',
            nombres='Final', apellidos='X',
        )
        usuario_negocio.clientes.add(self.cliente_propio)

        self.medio_propio = MedioPagoCliente.objects.create(
            cliente=self.cliente_propio, metodo_pago=self.metodo,
            alias='Mio', identificador='111',
        )
        self.medio_ajeno = MedioPagoCliente.objects.create(
            cliente=self.cliente_ajeno, metodo_pago=self.metodo,
            alias='Ajeno', identificador='222',
        )
        self.url = '/api/transacciones/medios-pago-cliente/'

    def _fijar_cliente_activo(self, cliente):
        session = self.client.session
        session[self.SESSION_KEY] = cliente.pk
        session.save()

    def test_usuario_final_solo_ve_los_suyos(self):
        self.client.force_authenticate(user=self.user_final)
        self._fijar_cliente_activo(self.cliente_propio)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        alias = {m['alias'] for m in resp.data['results']}
        self.assertEqual(alias, {'Mio'})

    def test_usuario_final_crea_siempre_para_su_propio_cliente(self):
        self.client.force_authenticate(user=self.user_final)
        self._fijar_cliente_activo(self.cliente_propio)
        resp = self.client.post(self.url, {
            'cliente': self.cliente_ajeno.pk,  # intenta colarse en otro cliente
            'metodo_pago': self.metodo.pk,
            'alias': 'Intento', 'identificador': '999',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        creado = MedioPagoCliente.objects.get(alias='Intento')
        self.assertEqual(creado.cliente, self.cliente_propio)  # se ignoro lo que mando

    def test_usuario_final_sin_ningun_cliente_asociado_no_puede_crear(self):
        # A diferencia de self.user_final (que tiene un solo cliente y por
        # eso RF43 se lo auto-selecciona), este usuario no tiene ninguno.
        sin_cliente = _usuario_con_rol('sin_cliente', rol='usuario_final')
        self.client.force_authenticate(user=sin_cliente)
        resp = self.client.post(self.url, {
            'cliente': self.cliente_propio.pk, 'metodo_pago': self.metodo.pk,
            'alias': 'x', 'identificador': 'y',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_administrador_ve_todos(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_mediopago2', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.data['count'], 2)

    def test_anonimo_no_tiene_acceso(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
