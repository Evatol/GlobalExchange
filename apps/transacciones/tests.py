from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from apps.divisas.models import Moneda, TasaCambio
from apps.usuarios.models import Cliente, Usuario
from .models import MedioPagoCliente, MetodoPago, Transaccion


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


class GestionMetodosPagoViewTests(TestCase):
    """Pantalla propia del catálogo de métodos de pago (en vez de la API navegable)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='BANCO')
        self.url = '/api/transacciones/gestion/metodos-pago/'

    def test_prohibido_para_analista(self):
        self.client.force_login(_usuario_con_rol('analista_gmp', rol='analista'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_ve_el_listado_y_puede_crear(self):
        self.client.force_login(_usuario_con_rol('admin_gmp', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Transferencia')

        resp = self.client.post(self.url, {'nombre': 'Efectivo', 'tipo': 'CASH', 'estado': 'on'})
        self.assertRedirects(resp, self.url)
        self.assertTrue(MetodoPago.objects.filter(nombre='Efectivo').exists())

    def test_toggle(self):
        self.client.force_login(_usuario_con_rol('admin_gmp2', rol='administrador'))
        self.client.post(f'/api/transacciones/gestion/metodos-pago/{self.metodo.id}/toggle/')
        self.metodo.refresh_from_db()
        self.assertFalse(self.metodo.estado)


class GestionMediosPagoViewTests(TestCase):
    """Pantalla propia de "Mis Medios de Pago" (en vez de la API navegable)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.cliente_propio = _cliente(nombre='Cliente Propio', documento='P2')
        self.cliente_ajeno = _cliente(nombre='Cliente Ajeno', documento='A2')

        self.user_final = _usuario_con_rol('final_gmedios', rol='usuario_final')
        usuario_negocio = Usuario.objects.create(
            username='final_gmedios', email='fg@example.com', nombres='F', apellidos='G',
        )
        usuario_negocio.clientes.add(self.cliente_propio)

        self.medio_propio = MedioPagoCliente.objects.create(
            cliente=self.cliente_propio, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )
        self.medio_ajeno = MedioPagoCliente.objects.create(
            cliente=self.cliente_ajeno, metodo_pago=self.metodo, alias='Ajeno', identificador='2',
        )
        self.url = '/api/transacciones/gestion/medios-pago-cliente/'

    def test_usuario_final_solo_ve_los_suyos_y_crea_para_si_mismo(self):
        self.client.force_login(self.user_final)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mio')
        self.assertNotContains(resp, 'Ajeno')

        resp = self.client.post(self.url, {
            'cliente': self.cliente_ajeno.pk,  # se ignora, se fuerza el propio
            'metodo_pago': self.metodo.pk, 'alias': 'Nuevo', 'identificador': '999',
        })
        self.assertRedirects(resp, self.url)
        creado = MedioPagoCliente.objects.get(alias='Nuevo')
        self.assertEqual(creado.cliente, self.cliente_propio)

    def test_administrador_ve_todos_con_columna_cliente(self):
        self.client.force_login(_usuario_con_rol('admin_gmedios', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Mio')
        self.assertContains(resp, 'Ajeno')
        self.assertContains(resp, 'Cliente Propio')

    def test_toggle_respeta_el_alcance(self):
        self.client.force_login(self.user_final)
        # intenta desactivar el medio de OTRO cliente
        self.client.post(f'/api/transacciones/gestion/medios-pago-cliente/{self.medio_ajeno.id}/toggle/')
        self.medio_ajeno.refresh_from_db()
        self.assertTrue(self.medio_ajeno.estado)  # no cambio, no era suyo


class MetodoPagoEditarViewTests(TestCase):
    """Edición de un método de pago existente."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='BANCO')
        self.url = f'/api/transacciones/gestion/metodos-pago/{self.metodo.id}/editar/'

    def test_prohibido_para_analista(self):
        self.client.force_login(_usuario_con_rol('analista_mpe', rol='analista'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_puede_editar(self):
        self.client.force_login(_usuario_con_rol('admin_mpe', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Transferencia')

        resp = self.client.post(self.url, {'nombre': 'Transferencia Bancaria', 'tipo': 'BANCO', 'estado': 'on'})
        self.assertRedirects(resp, '/api/transacciones/gestion/metodos-pago/')
        self.metodo.refresh_from_db()
        self.assertEqual(self.metodo.nombre, 'Transferencia Bancaria')


class MedioPagoEditarViewTests(TestCase):
    """Edición de un medio de pago existente, respetando el alcance por
    cliente activo (usuario_final no puede editar el de otro cliente)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.cliente_propio = _cliente(nombre='Cliente Propio', documento='P3')
        self.cliente_ajeno = _cliente(nombre='Cliente Ajeno', documento='A3')

        self.user_final = _usuario_con_rol('final_mpe', rol='usuario_final')
        usuario_negocio = Usuario.objects.create(
            username='final_mpe', email='fmpe@example.com', nombres='F', apellidos='M',
        )
        usuario_negocio.clientes.add(self.cliente_propio)

        self.medio_propio = MedioPagoCliente.objects.create(
            cliente=self.cliente_propio, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )
        self.medio_ajeno = MedioPagoCliente.objects.create(
            cliente=self.cliente_ajeno, metodo_pago=self.metodo, alias='Ajeno', identificador='2',
        )

    def test_usuario_final_puede_editar_el_suyo(self):
        self.client.force_login(self.user_final)
        url = f'/api/transacciones/gestion/medios-pago-cliente/{self.medio_propio.id}/editar/'
        resp = self.client.post(url, {
            'metodo_pago': self.metodo.id, 'alias': 'Mio Renombrado',
            'identificador': '1', 'titular': '', 'estado': 'on',
        })
        self.assertRedirects(resp, '/api/transacciones/gestion/medios-pago-cliente/')
        self.medio_propio.refresh_from_db()
        self.assertEqual(self.medio_propio.alias, 'Mio Renombrado')

    def test_usuario_final_no_puede_editar_el_de_otro_cliente(self):
        self.client.force_login(self.user_final)
        url = f'/api/transacciones/gestion/medios-pago-cliente/{self.medio_ajeno.id}/editar/'
        resp = self.client.get(url)
        # no esta en su alcance -> lo manda de vuelta al listado sin tocar nada
        self.assertRedirects(resp, '/api/transacciones/gestion/medios-pago-cliente/')
        self.medio_ajeno.refresh_from_db()
        self.assertEqual(self.medio_ajeno.alias, 'Ajeno')

    def test_administrador_puede_editar_cualquiera(self):
        self.client.force_login(_usuario_con_rol('admin_mpe2', rol='administrador'))
        url = f'/api/transacciones/gestion/medios-pago-cliente/{self.medio_ajeno.id}/editar/'
        resp = self.client.post(url, {
            'metodo_pago': self.metodo.id, 'alias': 'Ajeno Editado',
            'identificador': '2', 'titular': '', 'estado': 'on',
        })
        self.assertRedirects(resp, '/api/transacciones/gestion/medios-pago-cliente/')
        self.medio_ajeno.refresh_from_db()
        self.assertEqual(self.medio_ajeno.alias, 'Ajeno Editado')


class TransaccionCalculoComisionTests(TestCase):
    """E4-144: cálculo de tasas y comisión, diferenciada por la preferencia
    de tipo de cambio del cliente (RF41)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')

    def _transaccion(self, tipo, cliente=None, cantidad=Decimal('10'), tasa=Decimal('7300')):
        return Transaccion(
            cliente=cliente, moneda=self.moneda, metodo_pago=self.metodo,
            tipo=tipo, cantidad=cantidad, tasa_cambio=tasa,
        )

    def test_sin_cliente_usa_la_comision_por_defecto(self):
        tx = self._transaccion('COMPRA')
        desglose = tx.calcular_tasas_y_comisiones()
        self.assertEqual(tx.comision_porcentaje, Decimal('1.50'))
        self.assertEqual(desglose['subtotal'], Decimal('73000'))
        self.assertEqual(desglose['comision'], Decimal('1095.00'))
        self.assertEqual(desglose['monto_total'], Decimal('74095.00'))

    def test_cliente_estandar_paga_la_comision_mas_alta(self):
        cliente = Cliente.objects.create(
            nombre='Cliente Estandar', documento='E1', tipo='FISICA',
            preferencia_tipo_cambio=Cliente.PREFERENCIA_ESTANDAR,
        )
        tx = self._transaccion('COMPRA', cliente=cliente)
        tx.calcular_tasas_y_comisiones()
        self.assertEqual(tx.comision_porcentaje, Decimal('1.50'))

    def test_cliente_preferencial_paga_menos_comision(self):
        cliente = Cliente.objects.create(
            nombre='Cliente Preferencial', documento='P1', tipo='FISICA',
            preferencia_tipo_cambio=Cliente.PREFERENCIA_PREFERENCIAL,
        )
        tx = self._transaccion('COMPRA', cliente=cliente)
        tx.calcular_tasas_y_comisiones()
        self.assertEqual(tx.comision_porcentaje, Decimal('1.00'))

    def test_cliente_mayorista_paga_la_comision_mas_baja(self):
        cliente = Cliente.objects.create(
            nombre='Cliente Mayorista', documento='M1', tipo='FISICA',
            preferencia_tipo_cambio=Cliente.PREFERENCIA_MAYORISTA,
        )
        tx = self._transaccion('COMPRA', cliente=cliente)
        tx.calcular_tasas_y_comisiones()
        self.assertEqual(tx.comision_porcentaje, Decimal('0.50'))

    def test_venta_resta_la_comision_en_vez_de_sumarla(self):
        tx = self._transaccion('VENTA', cantidad=Decimal('10'), tasa=Decimal('7300'))
        desglose = tx.calcular_tasas_y_comisiones()
        self.assertEqual(desglose['subtotal'], Decimal('73000'))
        self.assertEqual(desglose['monto_total'], Decimal('73000') - desglose['comision'])


class OperarDivisaViewTests(TestCase):
    """E4-19/E4-20: comprar y vender divisas de forma digital, con la
    comisión y tasa aplicada según el cliente (E4-144)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(nombre='Cliente Propio', documento='OP1')
        self.otro_cliente = _cliente(nombre='Cliente Ajeno', documento='OP2')

        self.user_final = _usuario_con_rol('final_operar', rol='usuario_final')
        self.usuario_negocio = Usuario.objects.create(
            username='final_operar', email='fo@example.com', nombres='F', apellidos='O',
        )
        self.usuario_negocio.clientes.add(self.cliente)

        self.medio_propio = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )
        self.medio_ajeno = MedioPagoCliente.objects.create(
            cliente=self.otro_cliente, metodo_pago=self.metodo, alias='Ajeno', identificador='2',
        )
        self.url = '/api/transacciones/gestion/operar/'

    def _comprar(self, **overrides):
        datos = dict(
            tipo='COMPRA', moneda_codigo='USD', cantidad='10',
            medio_pago_id=self.medio_propio.id,
        )
        datos.update(overrides)
        return self.client.post(self.url, datos)

    def test_requiere_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_comprar_crea_la_transaccion_con_el_usuario_de_negocio_correcto(self):
        self.client.force_login(self.user_final)
        resp = self._comprar()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'realizada con éxito')

        tx = Transaccion.objects.get(cliente=self.cliente)
        self.assertEqual(tx.usuario, self.usuario_negocio)  # no el auth.User
        self.assertEqual(tx.tipo, 'COMPRA')
        self.assertEqual(tx.tasa_cambio, Decimal('7300'))
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_vender_usa_la_tasa_de_venta(self):
        self.client.force_login(self.user_final)
        resp = self._comprar(tipo='VENTA')
        self.assertEqual(resp.status_code, 200)
        tx = Transaccion.objects.get(cliente=self.cliente, tipo='VENTA')
        self.assertEqual(tx.tasa_cambio, Decimal('7400'))

    def test_no_puede_usar_el_medio_de_pago_de_otro_cliente(self):
        self.client.force_login(self.user_final)
        resp = self._comprar(medio_pago_id=self.medio_ajeno.id)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'no es válido')
        self.assertFalse(Transaccion.objects.filter(cliente=self.cliente).exists())

    def test_cantidad_invalida_no_crea_transaccion(self):
        self.client.force_login(self.user_final)
        resp = self._comprar(cantidad='0')
        self.assertContains(resp, 'mayor a 0')
        self.assertFalse(Transaccion.objects.exists())

    def test_sin_cliente_activo_no_puede_operar(self):
        sin_cliente = _usuario_con_rol('sin_cliente_operar', rol='usuario_final')
        Usuario.objects.create(username='sin_cliente_operar', email='sc@example.com', nombres='S', apellidos='C')
        self.client.force_login(sin_cliente)
        resp = self._comprar()
        self.assertContains(resp, 'cliente activo')
        self.assertFalse(Transaccion.objects.exists())


class OperarDivisaAPITests(APITestCase):
    """Misma lógica que OperarDivisaViewTests, pero contra el endpoint API
    (``OperarDivisaAPIView`` / ``CalcularTransaccionAPIView``)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='CASH')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(nombre='Cliente Propio', documento='API1')
        self.user_final = _usuario_con_rol('final_api_operar', rol='usuario_final')
        self.usuario_negocio = Usuario.objects.create(
            username='final_api_operar', email='fa@example.com', nombres='F', apellidos='A',
        )
        self.usuario_negocio.clientes.add(self.cliente)
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )

    def test_calcular_no_persiste_nada(self):
        self.client.force_authenticate(user=self.user_final)
        resp = self.client.post('/api/transacciones/calcular/', {
            'moneda_codigo': 'USD', 'cantidad': '10', 'tipo': 'COMPRA',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['monto_total'], Decimal('74095.00'))
        self.assertFalse(Transaccion.objects.exists())

    def test_operar_crea_la_transaccion(self):
        self.client.force_authenticate(user=self.user_final)
        resp = self.client.post('/api/transacciones/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10',
            'medio_pago_id': self.medio.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        tx = Transaccion.objects.get(id=resp.data['transaccion_id'])
        self.assertEqual(tx.usuario, self.usuario_negocio)
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_requiere_autenticacion(self):
        resp = self.client.post('/api/transacciones/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10',
            'medio_pago_id': self.medio.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TransaccionCancelacionPorCambioDeTasaTests(TestCase):
    """E4-28: la transacción se cancela sola si la cotización cambió entre
    que se creó y que se intenta confirmar/pagar."""

    def setUp(self):
        self.usuario = Usuario.objects.create(
            username='testuser_e428', email='test_e428@mail.com',
            nombres='Test', apellidos='User',
        )
        self.cliente = _cliente(nombre='Cliente E4-28', documento='E428')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$', estado=True)
        self.tasa_cambio_obj = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300.00'), tasa_venta=Decimal('7400.00'),
            origen='Banco Central', estado=True,
        )
        self.metodo_pago = MetodoPago.objects.create(nombre='Efectivo', tipo='Fisico', estado=True)

    def _transaccion_pendiente(self):
        return Transaccion.objects.create(
            usuario=self.usuario, cliente=self.cliente, moneda=self.moneda,
            metodo_pago=self.metodo_pago, tipo='COMPRA', cantidad=Decimal('10.00'),
            tasa_cambio=Decimal('7300.00'), modalidad='DIGITAL',
        )

    def test_cancelar_transaccion_si_cambia_tasa(self):
        transaccion = self._transaccion_pendiente()

        # Simulamos que la tasa de compra cambia antes de confirmar
        self.tasa_cambio_obj.tasa_compra = Decimal('7450.00')
        self.tasa_cambio_obj.save()

        with self.assertRaises(ValidationError):
            transaccion.confirmar()

        transaccion.refresh_from_db()
        self.assertEqual(transaccion.estado, 'CANCELADA')

    def test_confirma_normal_si_la_tasa_no_cambio(self):
        transaccion = self._transaccion_pendiente()

        transaccion.confirmar()

        transaccion.refresh_from_db()
        self.assertEqual(transaccion.estado, 'EXITOSA')
        self.assertGreater(transaccion.monto_total, Decimal('0'))
