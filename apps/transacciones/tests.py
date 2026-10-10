import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.template.defaultfilters import floatformat
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
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA')

    def test_crear_y_listar(self):
        resp = self.client.post(
            self.url, {'nombre': 'Billetera', 'tipo': 'BILLETERA'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(self.client.get(self.url).data['count'], 2)

    def test_borrado_logico(self):
        resp = self.client.delete(f'{self.url}{self.metodo.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.metodo.refresh_from_db()
        self.assertFalse(self.metodo.estado)
        self.assertTrue(MetodoPago.objects.filter(pk=self.metodo.pk).exists())

    def test_tipo_fuera_del_catalogo_se_rechaza(self):
        """El tipo decide si se cobra por el banco: ya no es texto libre."""
        resp = self.client.post(
            self.url, {'nombre': 'Cheque', 'tipo': 'CHEQUE'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tipo', resp.data)

    def test_filtrar_por_tipo(self):
        MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        resp = self.client.get(self.url, {'tipo': 'EFECTIVO'})
        self.assertEqual(resp.data['count'], 1)


class MedioPagoClienteCRUDTests(APITestCase):
    """RF17: medios de pago de un cliente."""

    def setUp(self):
        self.client.force_authenticate(user=_usuario_con_rol('admin_mediopago', rol='administrador'))
        self.url = '/api/transacciones/medios-pago-cliente/'
        self.cliente = _cliente()
        self.otro_cliente = _cliente(nombre='Otro', documento='999')
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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
        self.assertEqual(resp.data['metodo_pago_nombre'], 'Efectivo')

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
        self.payload = {'nombre': 'Tarjeta de crédito', 'tipo': 'TARJETA_CREDITO'}

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

        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA')
        self.url = '/api/transacciones/gestion/metodos-pago/'

    def test_prohibido_para_analista(self):
        self.client.force_login(_usuario_con_rol('analista_gmp', rol='analista'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_ve_el_listado_y_puede_crear(self):
        self.client.force_login(_usuario_con_rol('admin_gmp', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Transferencia')

        resp = self.client.post(self.url, {'nombre': 'Efectivo', 'tipo': 'EFECTIVO', 'estado': 'on'})
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
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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

    def test_medio_repetido_se_rechaza_con_un_mensaje_claro(self):
        """Antes salía "Los campos cliente, metodo_pago, identificador deben
        formar un conjunto único.", con nombres internos de los campos."""
        self.client.force_login(self.user_final)
        resp = self.client.post(self.url, {
            'metodo_pago': self.metodo.pk, 'alias': 'Otro', 'identificador': '1',
        })
        self.assertContains(resp, 'Ese cliente ya tiene registrado ese medio de pago.')
        self.assertNotContains(resp, 'conjunto único')
        self.assertEqual(MedioPagoCliente.objects.filter(cliente=self.cliente_propio).count(), 1)

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
        self.metodo = MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA')
        self.url = f'/api/transacciones/gestion/metodos-pago/{self.metodo.id}/editar/'

    def test_prohibido_para_analista(self):
        self.client.force_login(_usuario_con_rol('analista_mpe', rol='analista'))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_puede_editar(self):
        self.client.force_login(_usuario_con_rol('admin_mpe', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Transferencia')

        resp = self.client.post(self.url, {'nombre': 'Transferencia Bancaria', 'tipo': 'TRANSFERENCIA', 'estado': 'on'})
        self.assertRedirects(resp, '/api/transacciones/gestion/metodos-pago/')
        self.metodo.refresh_from_db()
        self.assertEqual(self.metodo.nombre, 'Transferencia Bancaria')


class MedioPagoEditarViewTests(TestCase):
    """Edición de un medio de pago existente, respetando el alcance por
    cliente activo (usuario_final no puede editar el de otro cliente)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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

    def test_los_montos_quedan_con_dos_decimales(self):
        """La tasa tiene 6 decimales: sin redondear, los montos arrastraban
        esa precisión y se mostraban como '67935.99000000' en pantalla."""
        tx = self._transaccion('COMPRA', cantidad=Decimal('9.26'), tasa=Decimal('7300.000000'))
        desglose = tx.calcular_tasas_y_comisiones()
        for clave, valor in desglose.items():
            self.assertEqual(
                valor.as_tuple().exponent, -2,
                f'{clave} deberia tener exactamente 2 decimales, vino {valor}',
            )
        # 9.26 x 7300 = 67.598,00 + 1,5% (1.013,97) = 68.611,97
        self.assertEqual(desglose['monto_total'], Decimal('68611.97'))

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
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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
        # follow=True: si la operación se crea, redirige a su resumen.
        return self.client.post(self.url, datos, follow=True)

    def test_requiere_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_comprar_crea_la_transaccion_con_el_usuario_de_negocio_correcto(self):
        self.client.force_login(self.user_final)
        resp = self._comprar()
        tx = Transaccion.objects.get(cliente=self.cliente)
        self.assertRedirects(resp, f'/api/transacciones/gestion/operar/{tx.pk}/')
        self.assertContains(resp, 'Pendiente de pago')

        self.assertEqual(tx.usuario, self.usuario_negocio)  # no el auth.User
        self.assertEqual(tx.tipo, 'COMPRA')
        self.assertEqual(tx.tasa_cambio, Decimal('7400'))  # el cliente compra a la tasa de venta
        self.assertEqual(tx.estado, 'PENDIENTE')  # hasta que se confirme el pago

    def test_vender_usa_la_tasa_de_compra_de_la_casa(self):
        self.client.force_login(self.user_final)
        resp = self._comprar(tipo='VENTA')
        self.assertEqual(resp.status_code, 200)
        tx = Transaccion.objects.get(cliente=self.cliente, tipo='VENTA')
        self.assertEqual(tx.tasa_cambio, Decimal('7300'))

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

    def test_muestra_el_cambio_del_dia(self):
        # una cotización anterior, ya reemplazada: no se tiene que mostrar
        TasaCambio.objects.filter(moneda=self.moneda).update(fecha_hora='2020-01-01T00:00:00Z')
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7310'), tasa_venta=Decimal('7410'),
            origen='BCP', estado=True,
        )
        self.client.force_login(self.user_final)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Cambio del Día')
        self.assertEqual(list(resp.context['tasas'].values_list('tasa_venta', flat=True)), [Decimal('7410')])
        self.assertContains(resp, floatformat(Decimal('7410'), 2))
        self.assertNotContains(resp, floatformat(Decimal('7400'), 2))

    def test_el_cambio_del_dia_se_lee_desde_el_cliente(self):
        """El cliente compra a la tasa de venta de la casa (7.400) y vende a la
        de compra (7.300): las columnas lo dicen así y en ese orden."""
        self.client.force_login(self.user_final)
        html = self.client.get(self.url).content.decode()
        self.assertIn('COMPRÁS A', html)
        self.assertIn('VENDÉS A', html)
        self.assertNotIn('<th>COMPRA</th>', html)
        self.assertLess(
            html.index(floatformat(Decimal('7400'), 2)), html.index(floatformat(Decimal('7300'), 2))
        )

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
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
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
        # 10 x 7400 (tasa de venta) = 74.000 + 1,5% (cliente estándar) = 75.110
        self.assertEqual(resp.data['monto_total'], Decimal('75110.00'))
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
        self.assertEqual(tx.estado, 'PENDIENTE')
        self.assertEqual(resp.data['subtotal'], Decimal('74000.00'))

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
        self.metodo_pago = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO', estado=True)

    def _transaccion_pendiente(self):
        return Transaccion.objects.create(
            usuario=self.usuario, cliente=self.cliente, moneda=self.moneda,
            metodo_pago=self.metodo_pago, tipo='COMPRA', cantidad=Decimal('10.00'),
            tasa_cambio=Decimal('7400.00'), modalidad='DIGITAL',  # COMPRA -> tasa de venta
        )

    def test_cancelar_transaccion_si_cambia_tasa(self):
        transaccion = self._transaccion_pendiente()

        # Simulamos que cambia la tasa que se le aplica a una compra (la de
        # venta de la casa) antes de confirmar.
        self.tasa_cambio_obj.tasa_venta = Decimal('7450.00')
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


class HistorialTransaccionesTests(TestCase):
    """E4-104/E4-36: historial de transacciones (solo consulta) y su
    exportación a CSV/Excel/PDF, con el mismo alcance por rol que el resto
    de las pantallas de gestión."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$', estado=True)
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(nombre='Cliente Propio', documento='H1')
        self.otro_cliente = _cliente(nombre='Cliente Ajeno', documento='H2')

        self.user_final = _usuario_con_rol('final_historial', rol='usuario_final')
        usuario_negocio = Usuario.objects.create(
            username='final_historial', email='fh@example.com', nombres='F', apellidos='H',
        )
        usuario_negocio.clientes.add(self.cliente)

        Transaccion.objects.create(
            usuario=usuario_negocio, cliente=self.cliente, moneda=self.moneda, metodo_pago=self.metodo,
            tipo='COMPRA', cantidad=Decimal('10'), tasa_cambio=Decimal('7300'), monto_total=Decimal('73000'),
            modalidad='DIGITAL',
        )
        Transaccion.objects.create(
            usuario=usuario_negocio, cliente=self.otro_cliente, moneda=self.moneda, metodo_pago=self.metodo,
            tipo='VENTA', cantidad=Decimal('5'), tasa_cambio=Decimal('7400'), monto_total=Decimal('37000'),
            modalidad='DIGITAL',
        )
        self.url = '/api/transacciones/gestion/historial/'

    def test_requiere_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_administrador_ve_todas_las_transacciones(self):
        self.client.force_login(_usuario_con_rol('admin_historial', rol='administrador'))
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['transacciones']), 2)

    def test_usuario_final_solo_ve_las_de_su_cliente(self):
        self.client.force_login(self.user_final)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        transacciones = resp.context['transacciones']
        self.assertEqual(len(transacciones), 1)
        self.assertEqual(transacciones[0].cliente, self.cliente)

    def test_filtro_por_tipo(self):
        self.client.force_login(_usuario_con_rol('admin_historial2', rol='administrador'))
        resp = self.client.get(self.url, {'tipo': 'VENTA'})
        self.assertEqual(len(resp.context['transacciones']), 1)
        self.assertEqual(resp.context['transacciones'][0].tipo, 'VENTA')

    def test_exportar_csv(self):
        self.client.force_login(_usuario_con_rol('admin_historial3', rol='administrador'))
        resp = self.client.get('/api/transacciones/transacciones/exportar/?formato=csv')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')

    def test_exportar_excel(self):
        self.client.force_login(_usuario_con_rol('admin_historial4', rol='administrador'))
        resp = self.client.get('/api/transacciones/transacciones/exportar/?formato=excel')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertGreater(len(resp.content), 0)

    def test_exportar_pdf(self):
        self.client.force_login(_usuario_con_rol('admin_historial5', rol='administrador'))
        resp = self.client.get('/api/transacciones/transacciones/exportar/?formato=pdf')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertGreater(len(resp.content), 0)

    def test_formato_no_soportado(self):
        self.client.force_login(_usuario_con_rol('admin_historial6', rol='administrador'))
        resp = self.client.get('/api/transacciones/transacciones/exportar/?formato=xml')
        self.assertEqual(resp.status_code, 400)


class LimitesPorCategoriaTests(TestCase):
    """E4-143 (RF41): el monto de cada operación no puede superar el límite
    de la categoría del cliente: Minorista 100.000 Gs, Mayorista
    1.000.000 Gs, VIP sin límite. Aplica a compras y ventas por igual."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        # Minorista por defecto, con comisión estándar (1,5%).
        self.cliente = _cliente(nombre='Cliente Con Limite', documento='LIM1')
        self.user_final = _usuario_con_rol('final_limites', rol='usuario_final')
        self.usuario_negocio = Usuario.objects.create(
            username='final_limites', email='fl@example.com', nombres='F', apellidos='L',
        )
        self.usuario_negocio.clientes.add(self.cliente)
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )
        self.url = '/api/transacciones/gestion/operar/'
        self.client.force_login(self.user_final)

    def _operar(self, tipo='COMPRA', cantidad='10'):
        # follow=True: si pasa la validación, redirige al resumen pendiente.
        return self.client.post(self.url, {
            'tipo': tipo, 'moneda_codigo': 'USD', 'cantidad': cantidad,
            'medio_pago_id': self.medio.id,
        }, follow=True)

    def _categoria(self, categoria):
        self.cliente.actualizar_categoria(categoria)

    def test_minorista_dentro_del_limite(self):
        # 10 x 7400 = 74.000 + 1,5% = 75.110 <= 100.000
        resp = self._operar(cantidad='10')
        self.assertContains(resp, 'Pendiente de pago')

    def test_minorista_que_supera_100_mil_se_rechaza(self):
        # 14 x 7400 = 103.600 + 1,5% = 105.154 > 100.000
        resp = self._operar(cantidad='14')
        self.assertContains(resp, 'supera el límite por operación de la categoría Minorista')
        self.assertFalse(Transaccion.objects.exists())  # no queda registrada

    def test_el_limite_tambien_aplica_a_la_venta(self):
        # 14 x 7300 = 102.200 - 1,5% = 100.667 > 100.000
        resp = self._operar(tipo='VENTA', cantidad='14')
        self.assertContains(resp, 'supera el límite por operación')
        self.assertFalse(Transaccion.objects.exists())

    def test_mayorista_puede_hasta_un_millon(self):
        self._categoria(Cliente.CATEGORIA_MAYORISTA)
        # 14 USD (105.154) ya no supera el límite...
        self.assertContains(self._operar(cantidad='14'), 'Pendiente de pago')
        # ...pero 134 x 7400 = 991.600 + 1,5% = 1.006.474 sí.
        resp = self._operar(cantidad='134')
        self.assertContains(resp, 'supera el límite por operación de la categoría Mayorista')
        self.assertEqual(Transaccion.objects.count(), 1)

    def test_vip_no_tiene_limite(self):
        self._categoria(Cliente.CATEGORIA_VIP)
        # 1000 x 7400 = 7.400.000 + 1,5% = 7.511.000
        resp = self._operar(cantidad='1000')
        self.assertContains(resp, 'Pendiente de pago')
        self.assertEqual(Transaccion.objects.get().monto_total, Decimal('7511000.00'))

    def test_la_pantalla_muestra_la_categoria_y_su_limite(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Categoría Minorista')
        self.assertContains(resp, f'{floatformat(Decimal("100000"), "0g")} Gs')

    def test_tambien_aplica_en_el_endpoint_api(self):
        resp = self.client.post('/api/transacciones/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '14',
            'medio_pago_id': self.medio.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('supera el límite', resp.data['error'])
        self.assertFalse(Transaccion.objects.exists())


class ConfirmacionDePagoTests(TestCase):
    """E4-28 en la interfaz: la operación queda PENDIENTE, se ve el desglose
    y el pago se confirma (o se cancela si la cotización cambió) desde la
    pantalla. También la cancelación a pedido del cliente (RF23)."""

    def setUp(self):
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.tasa = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(
            nombre='Cliente Pago', documento='PG1',
            preferencia_tipo_cambio=Cliente.PREFERENCIA_MAYORISTA,
        )
        self.otro_cliente = _cliente(nombre='Cliente Ajeno Pago', documento='PG2')
        self.user_final = _usuario_con_rol('final_pago', rol='usuario_final')
        usuario_negocio = Usuario.objects.create(
            username='final_pago', email='fp@example.com', nombres='F', apellidos='P',
        )
        usuario_negocio.clientes.add(self.cliente)
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=self.metodo, alias='Mio', identificador='1',
        )
        self.client.force_login(self.user_final)

    def _iniciar(self, tipo='COMPRA', cantidad='13'):
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': tipo, 'moneda_codigo': 'USD', 'cantidad': cantidad,
            'medio_pago_id': self.medio.id,
        })
        return Transaccion.objects.latest('id')

    def _url(self, tx, accion=''):
        return f'/api/transacciones/gestion/operar/{tx.pk}/{accion}'

    def test_el_resumen_es_simple_cuanto_compra_cuanto_paga_y_con_que(self):
        tx = self._iniciar()
        resp = self.client.get(self._url(tx))
        # 13 x 7400 (tasa de venta) = 96.200 + 0,5% (mayorista) = 481 -> 96.681.
        # Los montos se comparan con el mismo filtro que usa el template, para
        # no depender del separador de miles del idioma configurado.
        for texto in ('Pendiente de pago', 'Comprás', floatformat(Decimal('13'), '2g'),
                      'Pagás', f'{floatformat(Decimal("96681"), "2g")} Gs', 'Mio',
                      f'1 USD = {floatformat(Decimal("7400"), "0g")} Gs',
                      'comisión 0,50% incluida', 'Confirmar pago', 'Cancelar operación'):
            self.assertContains(resp, texto)
        # sin el desglose paso a paso
        self.assertNotContains(resp, 'Subtotal')
        self.assertNotContains(resp, floatformat(Decimal('96200'), '2g'))

    def test_el_resumen_se_muestra_una_sola_vez(self):
        """Un error al editar el template dejaba pegada una segunda copia
        (vieja) del resumen debajo de la primera."""
        tx = self._iniciar()
        self.client.post(self._url(tx, 'confirmar/'))
        resp = self.client.get(self._url(tx))
        html = resp.content.decode()
        self.assertEqual(html.count(f'<h2>Operación #{tx.pk}</h2>'), 1)
        self.assertEqual(html.count('class="card shadow-sm border-0"'), 1)
        self.assertEqual(html.count('Nueva operación'), 1)

    def test_confirmar_sin_cambio_de_cotizacion_queda_exitosa(self):
        tx = self._iniciar()
        resp = self.client.post(self._url(tx, 'confirmar/'), follow=True)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')
        self.assertContains(resp, 'Pago confirmado')
        self.assertNotContains(resp, 'Confirmar pago')  # ya no se puede volver a pagar

    def test_si_la_cotizacion_cambio_al_confirmar_se_cancela(self):
        tx = self._iniciar()
        self.tasa.tasa_compra = Decimal('7350')
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()

        resp = self.client.post(self._url(tx, 'confirmar/'), follow=True)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')
        self.assertContains(resp, 'se inició a 7400.00 y la vigente es 7450.00')

    def test_una_cancelada_no_revive_aunque_la_cotizacion_vuelva(self):
        tx = self._iniciar()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        self.client.post(self._url(tx, 'confirmar/'))
        self.tasa.tasa_venta = Decimal('7400')  # vuelve al valor original
        self.tasa.save()

        self.client.post(self._url(tx, 'confirmar/'))
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')

    def test_el_cliente_puede_cancelar_antes_de_pagar(self):
        tx = self._iniciar()
        resp = self.client.post(self._url(tx, 'cancelar/'), follow=True)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')
        self.assertContains(resp, f'Cancelaste la operación #{tx.pk}')

    def test_no_se_puede_cancelar_una_ya_pagada(self):
        tx = self._iniciar()
        self.client.post(self._url(tx, 'confirmar/'))
        resp = self.client.post(self._url(tx, 'cancelar/'), follow=True)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')
        self.assertContains(resp, 'Solo se puede cancelar una transacción pendiente')

    def test_confirmar_y_cancelar_solo_aceptan_post(self):
        tx = self._iniciar()
        self.assertEqual(self.client.get(self._url(tx, 'confirmar/')).status_code, 405)
        self.assertEqual(self.client.get(self._url(tx, 'cancelar/')).status_code, 405)

    def test_no_puede_ver_ni_pagar_la_operacion_de_otro_cliente(self):
        ajena = Transaccion.objects.create(
            usuario=Usuario.objects.get(username='final_pago'), cliente=self.otro_cliente,
            moneda=self.moneda, metodo_pago=self.metodo, tipo='COMPRA',
            cantidad=Decimal('1'), tasa_cambio=Decimal('7300'),
        )
        self.assertEqual(self.client.get(self._url(ajena)).status_code, 404)
        self.assertEqual(self.client.post(self._url(ajena, 'confirmar/')).status_code, 404)
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, 'PENDIENTE')

    def test_la_pantalla_de_operar_lista_las_pendientes(self):
        tx = self._iniciar()
        resp = self.client.get('/api/transacciones/gestion/operar/')
        self.assertContains(resp, 'Operaciones pendientes de pago')
        self.assertContains(resp, self._url(tx))

    def test_la_vista_previa_cobra_la_misma_comision_que_la_operacion_real(self):
        """Antes la vista previa ignoraba al cliente y cobraba siempre 1,5%."""
        previa = self.client.post('/api/transacciones/calcular/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '13',
        }).json()
        tx = self._iniciar()
        self.assertEqual(Decimal(str(previa['comision_porcentaje'])), Decimal('0.50'))  # mayorista
        self.assertEqual(Decimal(str(previa['monto_total'])), tx.monto_total)

    def test_api_confirmar_y_cancelar(self):
        tx = self._iniciar()
        resp = self.client.post(f'/api/transacciones/transacciones/{tx.pk}/confirmar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['estado'], 'EXITOSA')

        tx2 = self._iniciar()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        resp = self.client.post(f'/api/transacciones/transacciones/{tx2.pk}/confirmar/')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['estado'], 'CANCELADA')

        tx3 = self._iniciar()
        resp = self.client.post(f'/api/transacciones/transacciones/{tx3.pk}/cancelar/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['estado'], 'CANCELADA')


def _abrir_cuenta(numero, tipo, documento, saldo=Decimal('0'), linea=Decimal('0')):
    from apps.banco import services as banco
    return banco.abrir_cuenta(
        numero=numero, tipo=tipo, entidad='Banco Itaú', titular_documento=documento,
        titular_nombre='Titular', saldo=saldo, linea_credito=linea,
    )


class MedioPagoConBancoTests(APITestCase):
    """Salvo el efectivo, un medio de pago tiene que ser una cuenta del banco
    del tipo correcto y a nombre del cliente."""

    def setUp(self):
        from apps.banco.models import CuentaBancaria
        from apps.usuarios.sesion import SESSION_KEY
        self.SESSION_KEY = SESSION_KEY
        self.url = '/api/transacciones/medios-pago-cliente/'
        self.cliente = _cliente(nombre='Cliente Propio', documento='DOC-1')
        self.victima = _cliente(nombre='Otro Cliente', documento='DOC-2')
        self.tarjeta = MetodoPago.objects.create(nombre='Tarjeta de crédito', tipo='TARJETA_CREDITO')
        self.transferencia = MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA')
        _abrir_cuenta('TC-PROPIA', CuentaBancaria.TIPO_TARJETA_CREDITO, 'DOC-1', linea=Decimal('100000'))
        _abrir_cuenta('TC-VICTIMA', CuentaBancaria.TIPO_TARJETA_CREDITO, 'DOC-2', linea=Decimal('100000'))

        self.user_final = _usuario_con_rol('final_mpb', rol='usuario_final')
        usuario = Usuario.objects.create(
            username='final_mpb', email='mpb@example.com', nombres='F', apellidos='B',
        )
        usuario.clientes.add(self.cliente)
        self.client.force_authenticate(user=self.user_final)

    def _crear(self, **datos):
        payload = dict(metodo_pago=self.tarjeta.pk, alias='Visa', identificador='TC-PROPIA')
        payload.update(datos)
        return self.client.post(self.url, payload)

    def test_asocia_una_tarjeta_propia(self):
        resp = self._crear()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        medio = MedioPagoCliente.objects.get(alias='Visa')
        self.assertEqual(medio.disponible, Decimal('100000.00'))

    def test_rechaza_una_cuenta_que_no_existe_en_el_banco(self):
        resp = self._crear(identificador='NO-EXISTE')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identificador', resp.data)

    def test_rechaza_si_el_tipo_no_coincide(self):
        resp = self._crear(metodo_pago=self.transferencia.pk)  # TC-PROPIA es una tarjeta
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_puede_asociar_la_tarjeta_de_otro_cliente(self):
        resp = self._crear(identificador='TC-VICTIMA')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(MedioPagoCliente.objects.exists())

    def test_tampoco_mandando_el_id_del_otro_cliente(self):
        """El cliente se fuerza al activo *antes* de verificar la cuenta:
        si no, mandando el id de la víctima se pasaba la verificación."""
        resp = self._crear(cliente=self.victima.pk, identificador='TC-VICTIMA')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(MedioPagoCliente.objects.exists())

    def test_no_puede_pasar_su_medio_a_otro_cliente(self):
        medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=self.tarjeta, alias='Visa', identificador='TC-PROPIA',
        )
        resp = self.client.patch(f'{self.url}{medio.pk}/', {
            'cliente': self.victima.pk, 'identificador': 'TC-VICTIMA',
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        medio.refresh_from_db()
        self.assertEqual((medio.cliente, medio.identificador), (self.cliente, 'TC-PROPIA'))

    def test_el_efectivo_no_necesita_cuenta(self):
        efectivo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        resp = self._crear(metodo_pago=efectivo.pk, alias='Caja', identificador='EF-1')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(MedioPagoCliente.objects.get(alias='Caja').disponible)

    def test_la_pantalla_no_muestra_el_saldo_del_banco(self):
        self._crear()
        self.client.force_login(self.user_final)
        resp = self.client.get('/api/transacciones/gestion/medios-pago-cliente/')
        self.assertContains(resp, 'Visa')
        self.assertNotContains(resp, floatformat(Decimal('100000'), '0g'))
        self.assertNotContains(resp, 'Disponible')


class PagoConBancoTests(TestCase):
    """Al confirmar, el total se cobra (compra) o se paga (venta) en la
    cuenta del banco del medio de pago. Sin saldo suficiente la operación
    se rechaza y queda FALLIDA. La tarjeta de crédito no sirve para vender."""

    def setUp(self):
        from apps.banco.models import CuentaBancaria
        self.CuentaBancaria = CuentaBancaria
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.tasa = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        # Mayorista (límite 1.000.000) con comisión estándar (1,5%).
        self.cliente = _cliente(
            nombre='Cliente Banco', documento='BAN-1', categoria=Cliente.CATEGORIA_MAYORISTA,
        )
        self.user_final = _usuario_con_rol('final_banco_tx', rol='usuario_final')
        usuario = Usuario.objects.create(
            username='final_banco_tx', email='fbt@example.com', nombres='F', apellidos='T',
        )
        usuario.clientes.add(self.cliente)

        _abrir_cuenta('CA-1', CuentaBancaria.TIPO_CUENTA, 'BAN-1', saldo=Decimal('1000000'))
        _abrir_cuenta('TC-1', CuentaBancaria.TIPO_TARJETA_CREDITO, 'BAN-1', linea=Decimal('50000'))
        _abrir_cuenta('BI-1', CuentaBancaria.TIPO_BILLETERA, 'BAN-1')

        def medio(nombre, tipo, alias, identificador):
            metodo = MetodoPago.objects.create(nombre=nombre, tipo=tipo)
            return MedioPagoCliente.objects.create(
                cliente=self.cliente, metodo_pago=metodo, alias=alias, identificador=identificador,
            )
        self.cuenta = medio('Transferencia', 'TRANSFERENCIA', 'Cuenta Itaú', 'CA-1')
        self.tarjeta = medio('Tarjeta de crédito', 'TARJETA_CREDITO', 'Visa Itaú', 'TC-1')
        self.billetera = medio('Billetera', 'BILLETERA', 'Tigo Money', 'BI-1')
        self.efectivo = medio('Efectivo', 'EFECTIVO', 'Caja chica', 'EF-1')
        self.client.force_login(self.user_final)

    def _iniciar(self, medio, tipo='COMPRA', cantidad='10'):
        return self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': tipo, 'moneda_codigo': 'USD', 'cantidad': cantidad,
            'medio_pago_id': medio.id,
        }, follow=True)

    def _confirmar(self, tx):
        return self.client.post(f'/api/transacciones/gestion/operar/{tx.pk}/confirmar/', follow=True)

    def _saldo(self, numero):
        return self.CuentaBancaria.objects.get(numero=numero).saldo

    def test_la_compra_se_debita_de_la_cuenta(self):
        self._iniciar(self.cuenta)
        tx = Transaccion.objects.get()
        self.assertEqual(tx.medio_pago, self.cuenta)
        self.assertEqual(self._saldo('CA-1'), Decimal('1000000.00'))  # todavía no cobra

        resp = self._confirmar(tx)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')
        self.assertContains(resp, 'Pago confirmado')
        # 10 x 7400 = 74.000 + 1,5% = 75.110
        self.assertEqual(self._saldo('CA-1'), Decimal('924890.00'))
        movimiento = self.CuentaBancaria.objects.get(numero='CA-1').movimientos.first()
        self.assertEqual(movimiento.referencia, f'GE-OP-{tx.pk}')

    def test_sin_saldo_suficiente_la_operacion_queda_fallida(self):
        self._iniciar(self.tarjeta)  # 75.110 contra una línea de 50.000
        tx = Transaccion.objects.get()
        resp = self._confirmar(tx)
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'FALLIDA')
        self.assertContains(resp, 'Pago rechazado')
        self.assertContains(resp, 'Saldo insuficiente')
        self.assertIn('Visa Itaú', tx.observacion)
        # el rechazo no revela cuánto tiene la tarjeta
        self.assertNotContains(resp, floatformat(Decimal('50000'), '2g'))
        self.assertNotIn(floatformat(Decimal('50000'), '2g'), tx.observacion)
        self.assertEqual(self._saldo('TC-1'), Decimal('50000.00'))  # no se tocó
        self.assertNotContains(resp, 'Confirmar pago')  # ya no se puede reintentar

    def test_la_fallida_aparece_en_el_historial(self):
        self._iniciar(self.tarjeta)
        self._confirmar(Transaccion.objects.get())
        resp = self.client.get('/api/transacciones/gestion/historial/', {'estado': 'FALLIDA'})
        self.assertEqual(len(resp.context['transacciones']), 1)
        self.assertContains(resp, 'Fallida')
        self.assertContains(resp, 'Saldo insuficiente')

    def test_la_tarjeta_va_bajando_su_disponible(self):
        # 5 x 7400 = 37.000 + 1,5% = 37.555
        self._iniciar(self.tarjeta, cantidad='5')
        self._confirmar(Transaccion.objects.get())
        self.assertEqual(self._saldo('TC-1'), Decimal('12445.00'))
        # la segunda ya no entra
        self._iniciar(self.tarjeta, cantidad='5')
        self._confirmar(Transaccion.objects.latest('id'))
        self.assertEqual(Transaccion.objects.latest('id').estado, 'FALLIDA')
        self.assertEqual(self._saldo('TC-1'), Decimal('12445.00'))

    def test_la_venta_se_acredita_en_la_billetera(self):
        self._iniciar(self.billetera, tipo='VENTA')
        self._confirmar(Transaccion.objects.get())
        # 10 x 7300 = 73.000 - 1,5% = 71.905
        self.assertEqual(self._saldo('BI-1'), Decimal('71905.00'))

    def test_no_se_puede_vender_con_tarjeta_de_credito(self):
        resp = self._iniciar(self.tarjeta, tipo='VENTA')
        self.assertContains(resp, 'Las tarjetas de crédito no se pueden usar para vender divisas')
        self.assertFalse(Transaccion.objects.exists())

    def test_tampoco_por_la_api(self):
        resp = self.client.post('/api/transacciones/operar/', {
            'tipo': 'VENTA', 'moneda_codigo': 'USD', 'cantidad': '10',
            'medio_pago_id': self.tarjeta.id,
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tarjetas de crédito', resp.data['error'])

    def test_la_pantalla_marca_las_tarjetas_para_bloquearlas_en_la_venta(self):
        resp = self.client.get('/api/transacciones/gestion/operar/')
        self.assertContains(resp, 'data-tipo="TARJETA_CREDITO"')
        self.assertContains(resp, 'no se pueden usar para vender divisas')

    def test_operar_no_muestra_el_saldo_de_los_medios(self):
        resp = self.client.get('/api/transacciones/gestion/operar/')
        self.assertContains(resp, 'Cuenta Itaú (Transferencia)')
        # 50.000 es la línea de la tarjeta (el 1.000.000 de la cuenta coincide
        # con el límite de la categoría Mayorista, que sí se muestra).
        self.assertNotContains(resp, floatformat(Decimal('50000'), '0g'))
        self.assertNotContains(resp, 'disponible')

    def test_el_efectivo_no_pasa_por_el_banco(self):
        self._iniciar(self.efectivo)
        self._confirmar(Transaccion.objects.get())
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')

    def test_si_cambio_la_cotizacion_se_cancela_sin_cobrar(self):
        self._iniciar(self.cuenta)
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        self._confirmar(Transaccion.objects.get())
        self.assertEqual(Transaccion.objects.get().estado, 'CANCELADA')
        self.assertEqual(self._saldo('CA-1'), Decimal('1000000.00'))

    def test_confirmar_dos_veces_no_cobra_dos_veces(self):
        self._iniciar(self.cuenta)
        tx = Transaccion.objects.get()
        tx.confirmar()
        with self.assertRaises(ValidationError):
            Transaccion.objects.get(pk=tx.pk).confirmar()
        self.assertEqual(self._saldo('CA-1'), Decimal('924890.00'))

    def test_cuenta_desactivada_en_el_banco_queda_fallida(self):
        self._iniciar(self.cuenta)
        self.CuentaBancaria.objects.get(numero='CA-1').desactivar()
        self._confirmar(Transaccion.objects.get())
        tx = Transaccion.objects.get()
        self.assertEqual(tx.estado, 'FALLIDA')
        self.assertIn('inactiva', tx.observacion)

    def test_api_confirmar_sin_saldo_responde_409_fallida(self):
        self._iniciar(self.tarjeta)
        tx = Transaccion.objects.get()
        resp = self.client.post(f'/api/transacciones/transacciones/{tx.pk}/confirmar/')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['estado'], 'FALLIDA')
        self.assertIn('Saldo insuficiente', resp.json()['observacion'])


class CambioEntreDivisasTests(TestCase):
    """Cambio de una divisa por otra, pasando por el guaraní: la casa le
    compra la de origen (tasa de compra) y le vende la de destino (tasa de
    venta). Solo en efectivo: las cuentas del banco son en guaraníes."""

    def setUp(self):
        from apps.banco.models import CuentaBancaria
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.eur = Moneda.objects.create(codigo='EUR', nombre='Euro', simbolo='€')
        TasaCambio.objects.create(
            moneda=self.usd, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.tasa_eur = TasaCambio.objects.create(
            moneda=self.eur, tasa_compra=Decimal('7900'), tasa_venta=Decimal('8050'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(
            nombre='Cliente Cambio', documento='CAM-1', categoria=Cliente.CATEGORIA_MAYORISTA,
        )
        self.user_final = _usuario_con_rol('final_cambio', rol='usuario_final')
        usuario = Usuario.objects.create(
            username='final_cambio', email='fc@example.com', nombres='F', apellidos='C',
        )
        usuario.clientes.add(self.cliente)
        self.efectivo = MedioPagoCliente.objects.create(
            cliente=self.cliente, metodo_pago=MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO'),
            alias='Caja chica', identificador='EF-1',
        )
        _abrir_cuenta('CA-1', CuentaBancaria.TIPO_CUENTA, 'CAM-1', saldo=Decimal('1000000'))
        self.cuenta = MedioPagoCliente.objects.create(
            cliente=self.cliente,
            metodo_pago=MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA'),
            alias='Cuenta Itaú', identificador='CA-1',
        )
        self.client.force_login(self.user_final)

    def _cambiar(self, cantidad='100', origen='USD', destino='EUR', medio=None):
        return self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'CAMBIO', 'moneda_codigo': origen, 'moneda_destino_codigo': destino,
            'cantidad': cantidad, 'medio_pago_id': (medio or self.efectivo).id,
        }, follow=True)

    def test_calcula_cuanto_recibe_pasando_por_el_guarani(self):
        resp = self._cambiar()
        tx = Transaccion.objects.get()
        self.assertEqual(tx.tipo, 'CAMBIO')
        self.assertEqual((tx.moneda, tx.moneda_destino), (self.usd, self.eur))
        self.assertEqual(tx.tasa_cambio, Decimal('7300'))           # la casa compra USD
        self.assertEqual(tx.tasa_cambio_destino, Decimal('8050'))   # y vende EUR
        # 100 x 7300 = 730.000 - 1,5% (10.950) = 719.050 / 8050 = 89,3229 -> 89,32
        self.assertEqual(tx.monto_total, Decimal('719050.00'))
        self.assertEqual(tx.cantidad_destino, Decimal('89.32'))
        self.assertContains(resp, 'Entregás')
        self.assertContains(resp, f'{floatformat(Decimal("100"), "2g")} USD')
        self.assertContains(resp, 'Recibís')
        self.assertContains(resp, f'{floatformat(Decimal("89.32"), "2g")} EUR')

    def test_se_confirma_como_cualquier_operacion(self):
        self._cambiar()
        tx = Transaccion.objects.get()
        tx.confirmar()
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'EXITOSA')

    def test_si_cambia_la_cotizacion_de_destino_se_cancela(self):
        self._cambiar()
        self.tasa_eur.tasa_venta = Decimal('8100')
        self.tasa_eur.save()
        tx = Transaccion.objects.get()
        with self.assertRaises(ValidationError) as ctx:
            tx.confirmar()
        self.assertIn('EUR: se inició a 8050.00 y la vigente es 8100.00', ctx.exception.messages[0])
        tx.refresh_from_db()
        self.assertEqual(tx.estado, 'CANCELADA')

    def test_solo_en_efectivo(self):
        resp = self._cambiar(medio=self.cuenta)
        self.assertContains(resp, 'solo se puede hacer en efectivo')
        self.assertFalse(Transaccion.objects.exists())

    def test_las_monedas_tienen_que_ser_distintas(self):
        resp = self._cambiar(destino='USD')
        self.assertContains(resp, 'tienen que ser distintas')
        self.assertFalse(Transaccion.objects.exists())

    def test_exige_la_moneda_de_destino(self):
        resp = self._cambiar(destino='')
        self.assertContains(resp, 'Elegí la moneda que querés recibir')

    def test_aplica_el_limite_de_la_categoria(self):
        self.cliente.actualizar_categoria(Cliente.CATEGORIA_MINORISTA)
        # 14 x 7300 = 102.200 - 1,5% = 100.667 > 100.000
        resp = self._cambiar(cantidad='14')
        self.assertContains(resp, 'supera el límite por operación')

    def test_vista_previa_por_api(self):
        resp = self.client.post('/api/transacciones/calcular/', {
            'tipo': 'CAMBIO', 'moneda_codigo': 'USD', 'moneda_destino_codigo': 'EUR',
            'cantidad': '100',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data['cantidad_destino'], Decimal('89.32'))
        self.assertFalse(Transaccion.objects.exists())

    def test_el_historial_lo_encuentra_por_la_moneda_de_destino(self):
        self._cambiar()
        resp = self.client.get('/api/transacciones/gestion/historial/', {'moneda': self.eur.pk})
        self.assertEqual(len(resp.context['transacciones']), 1)
        self.assertContains(resp, 'USD → EUR')


class PagoExternoModeloTests(TestCase):
    """Los métodos de E4-157/E4-158 del modelo no dejan reabrir una operación
    ya terminada ni pagar por la pasarela lo que no corresponde."""

    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(nombre='Cliente Pasarela', documento='PAS-C')
        self.usuario = Usuario.objects.create(
            username='pas_user', email='pas@example.com', nombres='P', apellidos='U',
        )
        self.metodo = MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')

    def _tx(self, tipo='COMPRA', **extra):
        return Transaccion.objects.create(
            usuario=self.usuario, cliente=self.cliente, moneda=self.moneda,
            metodo_pago=self.metodo, tipo=tipo, cantidad=Decimal('10'),
            tasa_cambio=Decimal('7400') if tipo == 'COMPRA' else Decimal('7300'),
            monto_total=Decimal('75110'), **extra,
        )

    def test_iniciar_deja_la_operacion_esperando_el_pago(self):
        tx = self._tx()
        tx.iniciar_pago_externo('PAS-1')
        tx.refresh_from_db()
        self.assertEqual((tx.estado, tx.referencia_pago_externo), ('PENDIENTE_PAGO', 'PAS-1'))

    def test_no_se_inicia_sobre_una_operacion_ya_terminada(self):
        for estado in ('EXITOSA', 'CANCELADA', 'FALLIDA', 'PENDIENTE_PAGO'):
            with self.subTest(estado=estado):
                tx = self._tx(estado=estado)
                with self.assertRaises(ValidationError):
                    tx.iniciar_pago_externo(f'PAS-{estado}')
                tx.refresh_from_db()
                self.assertEqual(tx.estado, estado)

    def test_solo_las_compras_se_pagan_por_la_pasarela(self):
        for tipo in ('VENTA', 'CAMBIO'):
            with self.subTest(tipo=tipo), self.assertRaises(ValidationError):
                self._tx(tipo=tipo).iniciar_pago_externo(f'PAS-{tipo}')

    def test_el_webhook_no_reabre_una_cancelada_ni_una_fallida(self):
        for estado in ('CANCELADA', 'FALLIDA', 'EXITOSA', 'PENDIENTE'):
            with self.subTest(estado=estado):
                tx = self._tx(estado=estado)
                with self.assertRaises(ValidationError):
                    tx.confirmar_pago_webhook()
                tx.refresh_from_db()
                self.assertEqual(tx.estado, estado)

    def test_confirmar_pago_webhook_es_repetible(self):
        tx = self._tx(estado='PENDIENTE_PAGO')
        tx.confirmar_pago_webhook()
        tx.confirmar_pago_webhook()
        self.assertEqual(Transaccion.objects.get(pk=tx.pk).estado, 'PAGADO')


class WebhookPagoExternoTests(TestCase):
    """E4-157/E4-158: el cliente inicia el pago por la pasarela y el webhook,
    firmado, termina de confirmarlo. No hay doble cobro con el banco."""

    URL = '/api/transacciones/webhook/pago/'

    def setUp(self):
        from apps.banco.models import CuentaBancaria
        self.CuentaBancaria = CuentaBancaria
        self.moneda = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.tasa = TasaCambio.objects.create(
            moneda=self.moneda, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'),
            origen='BCP', estado=True,
        )
        self.cliente = _cliente(
            nombre='Cliente Webhook', documento='WH-1', categoria=Cliente.CATEGORIA_VIP,
        )
        self.user_final = _usuario_con_rol('final_webhook', rol='usuario_final')
        Usuario.objects.create(
            username='final_webhook', email='wh@example.com', nombres='W', apellidos='H',
        ).clientes.add(self.cliente)
        _abrir_cuenta('CA-WH', CuentaBancaria.TIPO_CUENTA, 'WH-1', saldo=Decimal('1000000'))
        self.medio = MedioPagoCliente.objects.create(
            cliente=self.cliente, alias='Cuenta',
            metodo_pago=MetodoPago.objects.create(nombre='Transferencia', tipo='TRANSFERENCIA'),
            identificador='CA-WH',
        )
        self.client.force_login(self.user_final)
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '10',
            'medio_pago_id': self.medio.id,
        })
        self.tx = Transaccion.objects.get()

    def _iniciar(self):
        resp = self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/pago-externo/')
        self.tx.refresh_from_db()
        return resp

    def _aviso(self, referencia=None, estado='PAGADO', firma=None, cuerpo=None):
        from . import webhook
        cuerpo = cuerpo if cuerpo is not None else json.dumps({
            'referencia': referencia or self.tx.referencia_pago_externo, 'estado': estado,
        }).encode()
        headers = {webhook.ENCABEZADO_FIRMA: firma if firma is not None else webhook.firmar(cuerpo)}
        # El webhook lo llama la pasarela, no el cliente logueado.
        return self.client_anonimo.post(
            self.URL, data=cuerpo, content_type='application/json', headers=headers,
        )

    @property
    def client_anonimo(self):
        from django.test import Client
        return Client()

    def _saldo(self):
        return self.CuentaBancaria.objects.get(numero='CA-WH').saldo

    def test_iniciar_el_pago_externo_desde_la_pantalla(self):
        resp = self._iniciar()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')
        self.assertTrue(self.tx.referencia_pago_externo.startswith('PAS-'))
        # lleva al cliente a la pantalla de pago de la pasarela
        self.assertRedirects(
            resp, f'/api/pasarela/pagar/{self.tx.referencia_pago_externo}/', fetch_redirect_response=False,
        )
        # y si vuelve sin pagar, el resumen muestra cómo seguir
        resumen = self.client.get(f'/api/transacciones/gestion/operar/{self.tx.pk}/')
        self.assertContains(resumen, self.tx.referencia_pago_externo)
        self.assertContains(resumen, 'Esperando el pago externo')
        self.assertContains(resumen, 'Ir a la pasarela para pagar')
        self.assertNotContains(resumen, 'Confirmar pago')  # ya no se confirma a mano

    def test_la_pasarela_confirma_y_la_operacion_queda_exitosa(self):
        self._iniciar()
        resp = self._aviso()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'EXITOSA')

    def test_no_se_cobra_dos_veces_la_pasarela_y_el_banco(self):
        self._iniciar()
        self._aviso()
        self.assertEqual(self._saldo(), Decimal('1000000.00'))  # el banco no se tocó
        self.assertFalse(self.CuentaBancaria.objects.get(numero='CA-WH').movimientos.exclude(
            concepto='Saldo inicial').exists())

    def test_el_pago_normal_sigue_debitando_el_banco(self):
        self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/confirmar/')
        self.assertLess(self._saldo(), Decimal('1000000.00'))

    def test_aviso_repetido_no_hace_nada_dos_veces(self):
        self._iniciar()
        self._aviso()
        resp = self._aviso()
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ya procesado', resp.json()['detail'])
        self.assertEqual(Transaccion.objects.get().estado, 'EXITOSA')

    def test_firma_invalida_se_rechaza_y_no_toca_nada(self):
        self._iniciar()
        for firma in ('x' * 64, 'firma-incorrecta'):
            with self.subTest(firma=firma):
                self.assertEqual(self._aviso(firma=firma).status_code, 403)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'PENDIENTE_PAGO')

    def test_sin_firma_se_rechaza(self):
        from django.test import Client
        self._iniciar()
        resp = Client().post(self.URL, data={'referencia': self.tx.referencia_pago_externo, 'estado': 'PAGADO'},
                             content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_firma_de_otro_cuerpo_no_sirve(self):
        """Reusar una firma válida con otro cuerpo (cambiar la referencia) falla."""
        from . import webhook
        self._iniciar()
        firma = webhook.firmar(b'{"referencia": "OTRA", "estado": "PAGADO"}')
        self.assertEqual(self._aviso(firma=firma).status_code, 403)

    def test_sin_secreto_configurado_se_rechaza_todo(self):
        self._iniciar()
        with self.settings(WEBHOOK_PAGO_SECRET=''):
            self.assertEqual(self._aviso(firma='').status_code, 403)
        self.assertEqual(Transaccion.objects.get().estado, 'PENDIENTE_PAGO')

    def test_no_pide_login_ni_csrf(self):
        """La pasarela no tiene sesión: la firma es la autenticación."""
        from django.test import Client
        self._iniciar()
        cuerpo = json.dumps({'referencia': self.tx.referencia_pago_externo, 'estado': 'PAGADO'}).encode()
        from . import webhook
        resp = Client(enforce_csrf_checks=True).post(
            self.URL, data=cuerpo, content_type='application/json',
            headers={webhook.ENCABEZADO_FIRMA: webhook.firmar(cuerpo)},
        )
        self.assertEqual(resp.status_code, 200)

    def test_referencia_desconocida(self):
        self.assertEqual(self._aviso(referencia='PAS-NO-EXISTE').status_code, 404)

    def test_cuerpo_invalido_o_estado_desconocido(self):
        from . import webhook
        no_json = b'no es json'
        self.assertEqual(self._aviso(cuerpo=no_json, firma=webhook.firmar(no_json)).status_code, 400)
        self.assertEqual(self._aviso(referencia='x', estado='QUIEN SABE').status_code, 400)

    def test_la_pasarela_rechaza_el_cobro(self):
        self._iniciar()
        resp = self._aviso(estado='RECHAZADO')
        self.assertEqual(resp.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'FALLIDA')
        self.assertIn('pasarela', self.tx.observacion)
        self.assertEqual(self._saldo(), Decimal('1000000.00'))

    def test_si_cambio_la_cotizacion_se_cancela_y_queda_para_devolver(self):
        self._iniciar()
        self.tasa.tasa_venta = Decimal('7450')
        self.tasa.save()
        resp = self._aviso()
        self.assertEqual(resp.status_code, 409)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.estado, 'CANCELADA')
        self.assertIn('debe devolverse', self.tx.observacion)
        self.assertIn(self.tx.referencia_pago_externo, self.tx.observacion)

    def test_el_pago_llega_tarde_a_una_operacion_cancelada(self):
        self._iniciar()
        self.client.post(f'/api/transacciones/gestion/operar/{self.tx.pk}/cancelar/')
        resp = self._aviso()
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Transaccion.objects.get().estado, 'CANCELADA')  # no revive

    def test_no_se_puede_iniciar_el_pago_externo_de_una_venta(self):
        self.client.post('/api/transacciones/gestion/operar/', {
            'tipo': 'VENTA', 'moneda_codigo': 'USD', 'cantidad': '10', 'medio_pago_id': self.medio.id,
        })
        venta = Transaccion.objects.get(tipo='VENTA')
        resp = self.client.post(f'/api/transacciones/gestion/operar/{venta.pk}/pago-externo/', follow=True)
        self.assertContains(resp, 'solo aplica a las compras')
        venta.refresh_from_db()
        self.assertEqual(venta.estado, 'PENDIENTE')

    def test_api_iniciar_pago_externo(self):
        resp = self.client.post(f'/api/transacciones/transacciones/{self.tx.pk}/iniciar-pago-externo/')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['estado'], 'PENDIENTE_PAGO')
        self.assertTrue(resp.json()['referencia_pago_externo'].startswith('PAS-'))
        # una segunda vez ya no se puede
        self.assertEqual(
            self.client.post(f'/api/transacciones/transacciones/{self.tx.pk}/iniciar-pago-externo/').status_code,
            409,
        )

    def test_no_puede_iniciar_el_pago_de_la_operacion_de_otro_cliente(self):
        otro = _cliente(nombre='Ajeno', documento='WH-2')
        ajena = Transaccion.objects.create(
            usuario=Usuario.objects.get(username='final_webhook'), cliente=otro, moneda=self.moneda,
            metodo_pago=self.medio.metodo_pago, tipo='COMPRA', cantidad=Decimal('1'),
            tasa_cambio=Decimal('7400'),
        )
        resp = self.client.post(f'/api/transacciones/gestion/operar/{ajena.pk}/pago-externo/')
        self.assertEqual(resp.status_code, 404)
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, 'PENDIENTE')

    def test_la_operacion_esperando_aparece_en_pendientes_y_en_el_historial(self):
        self._iniciar()
        resp = self.client.get('/api/transacciones/gestion/operar/')
        self.assertContains(resp, 'Operaciones pendientes de pago')
        resp = self.client.get('/api/transacciones/gestion/historial/')
        self.assertContains(resp, 'Pendiente de Pago Externo')
        self.assertContains(resp, 'bg-info')


class SimularWebhookPagoComandoTests(TestCase):
    """El comando que hace de pasarela firma con el mismo código que verifica
    el webhook: si se desalinearan, la demo dejaría de funcionar."""

    def test_el_aviso_que_firma_el_comando_lo_acepta_el_webhook(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        from . import webhook

        capturado = {}

        class Respuesta:
            status = 200
            def read(self): return b'{}'
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def falso_urlopen(pedido, timeout=None):
            capturado['cuerpo'] = pedido.data
            capturado['firma'] = pedido.get_header('X-signature')
            capturado['url'] = pedido.full_url
            return Respuesta()

        with mock.patch('urllib.request.urlopen', falso_urlopen):
            call_command('simular_webhook_pago', 'PAS-ABC', stdout=StringIO())
        self.assertTrue(webhook.firma_valida(capturado['cuerpo'], capturado['firma']))
        self.assertEqual(json.loads(capturado['cuerpo']), {'referencia': 'PAS-ABC', 'estado': 'PAGADO'})
        self.assertTrue(capturado['url'].endswith('/api/transacciones/webhook/pago/'))

        with mock.patch('urllib.request.urlopen', falso_urlopen):
            call_command('simular_webhook_pago', 'PAS-ABC', '--firma-invalida', stdout=StringIO())
        self.assertFalse(webhook.firma_valida(capturado['cuerpo'], capturado['firma']))
