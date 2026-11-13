from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.divisas.models import Moneda, Simulacion, TasaCambio
from apps.transacciones.models import Transaccion
from apps.usuarios.models import Cliente, Usuario

from . import services
from .models import Billete, Caja, MovimientoBillete, Sucursal, StockBillete, Terminal
from .test_sucursales import _login_con_rol

User = get_user_model()


class TerminalTestSetUp:
    def setUp(self):
        self.terminal_count = 0
        self.admin = _login_con_rol('admin-terminal', 'administrador')
        self.client.force_authenticate(self.admin)
        self.sucursal = Sucursal.objects.create(
            nombre='Central Terminal', direccion='Asunción'
        )
        self.usd = Moneda.objects.create(
            codigo='USD', nombre='Dólar', simbolo='$'
        )
        self.billete_100 = Billete.objects.create(
            moneda=self.usd, denominacion=Decimal('100')
        )
        self.billete_50 = Billete.objects.create(
            moneda=self.usd, denominacion=Decimal('50')
        )

    def crear_terminal(self, **extra):
        self.terminal_count += 1
        datos = {
            'nombre': f'Autoservicio Central {self.terminal_count}',
            'sucursal': self.sucursal.pk,
            'estado': Terminal.ACTIVA,
            'stock_inicial': {
                str(self.billete_100.pk): 3,
                str(self.billete_50.pk): 2,
            },
        }
        datos.update(extra)
        return self.client.post(reverse('terminal-list'), datos, format='json')

    def _terminal_creada(self):
        respuesta = self.crear_terminal()
        return Terminal.objects.get(pk=respuesta.data['id'])


class TerminalesTests(TerminalTestSetUp, APITestCase):
    def test_crea_terminal_con_caja_stock_y_movimientos_iniciales(self):
        respuesta = self.crear_terminal()

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
        terminal = Terminal.objects.get(pk=respuesta.data['id'])
        self.assertEqual(terminal.caja_id, respuesta.data['caja_id'])
        self.assertEqual(terminal.sucursal, self.sucursal)
        self.assertIsNone(terminal.caja.cajero)
        cantidades = {
            fila.billete_id: fila.cantidad
            for fila in StockBillete.objects.filter(caja=terminal.caja)
        }
        self.assertEqual(cantidades, {
            self.billete_100.pk: 3,
            self.billete_50.pk: 2,
        })
        self.assertEqual(
            MovimientoBillete.objects.filter(caja=terminal.caja, tipo='ENTRADA').count(),
            2,
        )

    def test_rechaza_denominacion_inactiva_sin_crear_recursos_parciales(self):
        self.billete_100.desactivar()
        respuesta = self.crear_terminal()

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Terminal.objects.count(), 0)
        self.assertEqual(Caja.objects.filter(terminal__isnull=False).count(), 0)

    def test_rechaza_crear_terminal_en_sucursal_inactiva(self):
        self.sucursal.desactivar()

        respuesta = self.crear_terminal()

        self.assertEqual(respuesta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Terminal.objects.count(), 0)

    def test_editar_sucursal_actualiza_tambien_la_caja(self):
        terminal = self.crear_terminal().data
        nueva_sucursal = Sucursal.objects.create(
            nombre='Norte Terminal', direccion='Luque'
        )

        respuesta = self.client.patch(
            reverse('terminal-detail', args=[terminal['id']]),
            {'sucursal': nueva_sucursal.pk},
            format='json',
        )

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        caja = Caja.objects.get(pk=terminal['caja_id'])
        self.assertEqual(caja.sucursal, nueva_sucursal)

    def test_baja_logica_preserva_terminal_caja_y_stock(self):
        terminal_data = self.crear_terminal().data

        respuesta = self.client.delete(
            reverse('terminal-detail', args=[terminal_data['id']])
        )

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        terminal = Terminal.objects.get(pk=terminal_data['id'])
        self.assertEqual(terminal.estado, Terminal.INACTIVA)
        self.assertTrue(Caja.objects.filter(pk=terminal_data['caja_id']).exists())
        self.assertEqual(terminal.caja.stock_billetes.count(), 2)

    def test_no_admin_no_puede_administrar_terminales(self):
        self.client.force_authenticate(_login_con_rol('usuario-terminal', 'usuario_final'))

        respuesta = self.client.get(reverse('terminal-list'))

        self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)


class OperatividadTerminalTests(TerminalTestSetUp, APITestCase):
    def test_inicio_publico_permite_terminal_activa(self):
        terminal = self._terminal_creada()
        self.client.force_authenticate(user=None)

        respuesta = self.client.post(
            reverse('terminal-iniciar-operacion', args=[terminal.pk])
        )

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertTrue(respuesta.data['operativa'])

    def test_inicio_bloqueado_en_terminal_inactiva_y_mantenimiento(self):
        for estado in (Terminal.INACTIVA, Terminal.MANTENIMIENTO):
            with self.subTest(estado=estado):
                self.client.force_authenticate(self.admin)
                terminal = self._terminal_creada()
                terminal.estado = estado
                terminal.save(update_fields=['estado'])
                self.client.force_authenticate(user=None)

                respuesta = self.client.post(
                    reverse('terminal-iniciar-operacion', args=[terminal.pk])
                )

                self.assertEqual(respuesta.status_code, status.HTTP_409_CONFLICT)
                self.assertFalse(respuesta.data.get('operativa', False))
                self.assertIn('Terminal no operativa', str(respuesta.data))

    def test_inicio_bloqueado_si_la_sucursal_esta_inactiva(self):
        terminal = self._terminal_creada()
        self.sucursal.desactivar()
        self.client.force_authenticate(user=None)

        respuesta = self.client.post(
            reverse('terminal-iniciar-operacion', args=[terminal.pk])
        )

        self.assertEqual(respuesta.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('sucursal está inactiva', str(respuesta.data))

    def test_pantalla_simulada_muestra_el_bloqueo(self):
        terminal = self._terminal_creada()
        terminal.estado = Terminal.MANTENIMIENTO
        terminal.save(update_fields=['estado'])

        respuesta = self.client.get(reverse('terminal_inicio', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_409_CONFLICT)
        self.assertContains(respuesta, 'Terminal no operativa', status_code=409)

    def test_kiosco_anonimo_muestra_tasas_y_simula_sin_transaccion(self):
        terminal = self._terminal_creada()
        TasaCambio.objects.create(
            moneda=self.usd,
            tasa_compra=Decimal('7300'),
            tasa_venta=Decimal('7400'),
            origen='BCP',
        )
        self.client.force_authenticate(user=None)

        pagina = self.client.get(reverse('terminal_inicio', args=[terminal.pk]))
        simulacion = self.client.post(
            reverse('terminal_inicio', args=[terminal.pk]),
            {
                'moneda_codigo': 'USD',
                'tipo_operacion': 'compra',
                'cantidad': '10',
            },
        )

        self.assertEqual(pagina.status_code, status.HTTP_200_OK)
        self.assertContains(pagina, 'Identificarme para operar')
        self.assertContains(pagina, 'USD')
        self.assertEqual(simulacion.status_code, status.HTTP_200_OK)
        self.assertContains(simulacion, 'Resultado de la Simulación')
        self.assertEqual(Simulacion.objects.count(), 1)
        self.assertFalse(Transaccion.objects.exists())
        self.assertContains(simulacion, 'no registra una compra ni una venta')

    def _usuario_terminal(self, username='cliente-terminal', rol='usuario_final',
                          bloqueado=False, estado=True, clientes=1):
        user = User.objects.create_user(username)
        if rol:
            group, _ = Group.objects.get_or_create(name=rol)
            user.groups.add(group)
        perfil = Usuario.objects.create(
            username=username,
            email=f'{username}@example.com',
            nombres='Cliente',
            apellidos='Terminal',
            telefono='0981000000',
            direccion='Asunción',
            bloqueado=bloqueado,
            estado=estado,
        )
        for index in range(clientes):
            cliente = Cliente.objects.create(
                nombre=f'Cliente {username} {index}',
                documento=f'{username}-{index}',
                tipo='FISICA',
            )
            perfil.clientes.add(cliente)
        return user, perfil

    def _entrar(self, usuario):
        """El usuario inicia sesión (Keycloak) y llega al ingreso de la terminal."""
        self.client.force_authenticate(user=None)
        self.client.force_login(usuario)

    def test_login_sin_cliente_redirige_a_keycloak(self):
        terminal = self._terminal_creada()
        self.client.force_authenticate(user=None)

        for nombre in ('terminal_ingreso', 'terminal_operar'):
            with self.subTest(pantalla=nombre):
                respuesta = self.client.get(reverse(nombre, args=[terminal.pk]))
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/oidc/authenticate/', respuesta.url)

    def test_usuario_con_un_cliente_puede_continuar_a_operar(self):
        terminal = self._terminal_creada()
        usuario, perfil = self._usuario_terminal()
        self._entrar(usuario)

        respuesta = self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))

        self.assertRedirects(respuesta, reverse('terminal_operar', args=[terminal.pk]))
        self.assertEqual(
            self.client.session['cliente_activo_id'],
            perfil.clientes.get().pk,
        )

    def test_usuario_con_varios_clientes_debe_elegir_cliente_asociado(self):
        terminal = self._terminal_creada()
        usuario, perfil = self._usuario_terminal(clientes=2)
        self._entrar(usuario)
        url_cliente = reverse('terminal_cliente', args=[terminal.pk])

        ingreso = self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))
        selector = self.client.get(url_cliente)
        ajeno = Cliente.objects.create(
            nombre='Cliente ajeno', documento='terminal-ajeno', tipo='FISICA'
        )
        inactivo = Cliente.objects.create(
            nombre='Cliente inactivo', documento='terminal-inactivo',
            tipo='FISICA', estado=False,
        )
        perfil.clientes.add(inactivo)
        denegado = self.client.post(url_cliente, {'cliente': ajeno.pk})
        inactivo_denegado = self.client.post(url_cliente, {'cliente': inactivo.pk})
        self.assertNotIn('cliente_activo_id', self.client.session)
        elegido = perfil.clientes.filter(estado=True).first()
        respuesta = self.client.post(url_cliente, {'cliente': elegido.pk})

        self.assertRedirects(
            ingreso, url_cliente, fetch_redirect_response=False
        )
        self.assertEqual(selector.status_code, status.HTTP_200_OK)
        self.assertTemplateUsed(selector, 'caja/terminal_cliente.html')
        # Un cliente que no es del usuario, o que está inactivo, no se puede elegir.
        for rechazo in (denegado, inactivo_denegado):
            self.assertContains(rechazo, 'Elegí uno de los clientes de la lista')
        self.assertRedirects(
            respuesta, reverse('terminal_operar', args=[terminal.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.session['cliente_activo_id'],
            elegido.pk,
        )

    def test_cuenta_bloqueada_recibe_403_con_mensaje(self):
        terminal = self._terminal_creada()
        usuario, _ = self._usuario_terminal(bloqueado=True)
        self._entrar(usuario)

        respuesta = self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertContains(
            respuesta,
            'Tu cuenta está bloqueada para operar',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    def test_cuenta_bloqueada_no_puede_ejecutar_operacion_en_el_kiosco(self):
        terminal = self._terminal_creada()
        usuario, perfil = self._usuario_terminal(
            username='bloqueado-en-api'
        )
        self._entrar(usuario)
        self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))
        perfil.bloqueado = True
        perfil.save(update_fields=['bloqueado'])

        respuesta = self.client.post(
            reverse('terminal_operar', args=[terminal.pk]),
            {
                'accion': 'confirmar', 'tipo': 'COMPRA',
                'moneda_codigo': 'USD', 'cantidad': '10',
            },
        )
        # Desde la sesión del kiosco tampoco se llega a la API de operaciones digitales.
        por_api = self.client.post('/api/transacciones/operar/', {}, format='json')

        self.assertContains(
            respuesta, 'cuenta está bloqueada', status_code=status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(por_api.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Transaccion.objects.exists())

    def test_perfil_inactivo_sin_rol_y_sin_clientes_reciben_un_mensaje_claro(self):
        terminal = self._terminal_creada()
        casos = (
            (
                self._usuario_terminal(username='perfil-inactivo', estado=False)[0],
                'Tu perfil está inactivo',
            ),
            (
                self._usuario_terminal(username='sin-rol', rol=None)[0],
                'no tiene el rol usuario_final',
            ),
        )
        self.client.force_authenticate(user=None)

        for usuario, mensaje in casos:
            with self.subTest(username=usuario.username):
                self.client.force_login(usuario)
                respuesta = self.client.get(
                    reverse('terminal_ingreso', args=[terminal.pk])
                )
                self.assertContains(
                    respuesta,
                    mensaje,
                    status_code=status.HTTP_403_FORBIDDEN,
                )

        # Sin clientes la pantalla de clientes se lo explica y solo le deja salir.
        sin_clientes = self._usuario_terminal(username='sin-clientes', clientes=0)[0]
        self.client.force_login(sin_clientes)
        self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))
        respuesta = self.client.get(reverse('terminal_cliente', args=[terminal.pk]))
        self.assertContains(respuesta, 'no está asociado a ningún cliente')

    def test_terminal_no_operativa_rechaza_el_acceso_autenticado(self):
        terminal = self._terminal_creada()
        terminal.estado = Terminal.MANTENIMIENTO
        terminal.save(update_fields=['estado'])
        usuario, _ = self._usuario_terminal()
        self._entrar(usuario)

        respuesta = self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_409_CONFLICT)
        self.assertContains(
            respuesta,
            'Terminal no operativa',
            status_code=status.HTTP_409_CONFLICT,
        )

    def test_operacion_se_bloquea_si_terminal_pasa_a_mantenimiento(self):
        terminal = self._terminal_creada()
        usuario, _ = self._usuario_terminal(username='terminal-a-mantenimiento')
        self._entrar(usuario)
        self.client.get(reverse('terminal_ingreso', args=[terminal.pk]))
        terminal.estado = Terminal.MANTENIMIENTO
        terminal.save(update_fields=['estado'])

        respuesta = self.client.post(
            reverse('terminal_operar', args=[terminal.pk]),
            {
                'accion': 'confirmar', 'tipo': 'COMPRA',
                'moneda_codigo': 'USD', 'cantidad': '10',
            },
        )

        self.assertContains(
            respuesta,
            'Terminal no operativa',
            status_code=status.HTTP_409_CONFLICT,
        )
        self.assertFalse(Transaccion.objects.exists())


class PantallaAdministrarTerminalesTests(TerminalTestSetUp, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=None)
        self.client.force_login(self.admin)

    def test_admin_crea_terminal_con_caja_desde_pantalla(self):
        respuesta = self.client.post(
            reverse('gestion_terminales'),
            {
                'nombre': 'Terminal HTML',
                'sucursal': str(self.sucursal.pk),
                'estado': Terminal.ACTIVA,
                f'stock_{self.billete_100.pk}': '4',
                f'stock_{self.billete_50.pk}': '',
            },
        )

        self.assertRedirects(respuesta, reverse('gestion_terminales'))
        terminal = Terminal.objects.get(nombre='Terminal HTML')
        self.assertEqual(
            StockBillete.objects.get(caja=terminal.caja, billete=self.billete_100).cantidad,
            4,
        )
        self.assertEqual(
            StockBillete.objects.get(caja=terminal.caja, billete=self.billete_50).cantidad,
            0,
        )

    def test_desactivar_desde_la_pantalla_cierra_la_caja_y_conserva_el_stock(self):
        terminal = self._terminal_creada()
        self.assertEqual(terminal.caja.estado, 'ABIERTA')

        respuesta = self.client.post(reverse('terminal_desactivar', args=[terminal.pk]))

        self.assertRedirects(respuesta, reverse('gestion_terminales'))
        terminal.refresh_from_db()
        terminal.caja.refresh_from_db()
        self.assertEqual(terminal.estado, Terminal.INACTIVA)
        self.assertEqual(terminal.caja.estado, 'CERRADA')
        self.assertEqual(terminal.caja.stock_billetes.count(), 2)

    def test_desactivar_una_terminal_que_no_existe_no_rompe(self):
        respuesta = self.client.post(reverse('terminal_desactivar', args=[9999]))
        self.assertRedirects(respuesta, reverse('gestion_terminales'))

    def test_pantalla_muestra_error_si_denominacion_inicial_no_esta_activa(self):
        self.billete_100.desactivar()

        respuesta = self.client.post(
            reverse('gestion_terminales'),
            {
                'nombre': 'Terminal con denominación inactiva',
                'sucursal': str(self.sucursal.pk),
                'estado': Terminal.ACTIVA,
                f'stock_{self.billete_100.pk}': '4',
            },
        )

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertContains(respuesta, 'denominaciones activas')
        self.assertEqual(Terminal.objects.count(), 0)

    def test_la_pantalla_de_una_terminal_activa_permite_identificarse(self):
        terminal = self._terminal_creada()

        respuesta = self.client.get(reverse('terminal_inicio', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertContains(respuesta, 'Identificarme para operar')


class CajaDeLaTerminalTests(TerminalTestSetUp, APITestCase):
    """La caja de una terminal está abierta mientras la terminal esté activa: así su
    stock cuenta como disponible para entregar billetes solo cuando puede operar."""

    def test_la_caja_de_una_terminal_activa_nace_abierta(self):
        terminal = self._terminal_creada()
        self.assertEqual(terminal.caja.estado, 'ABIERTA')
        self.assertIsNotNone(terminal.caja.fecha_apertura)

    def test_la_caja_de_una_terminal_que_no_esta_activa_nace_cerrada(self):
        for estado in (Terminal.INACTIVA, Terminal.MANTENIMIENTO):
            with self.subTest(estado=estado):
                respuesta = self.crear_terminal(estado=estado)
                caja = Terminal.objects.get(pk=respuesta.data['id']).caja
                self.assertEqual(caja.estado, 'CERRADA')

    def test_cambiar_el_estado_de_la_terminal_cierra_y_vuelve_a_abrir_su_caja(self):
        terminal = self._terminal_creada()
        url = reverse('terminal-detail', args=[terminal.pk])

        self.client.patch(url, {'estado': Terminal.MANTENIMIENTO}, format='json')
        terminal.caja.refresh_from_db()
        self.assertEqual(terminal.caja.estado, 'CERRADA')
        self.assertIsNotNone(terminal.caja.fecha_cierre)

        self.client.patch(url, {'estado': Terminal.ACTIVA}, format='json')
        terminal.caja.refresh_from_db()
        self.assertEqual(terminal.caja.estado, 'ABIERTA')
        self.assertIsNone(terminal.caja.fecha_cierre)

    def test_dar_de_baja_la_terminal_cierra_su_caja_sin_perder_el_stock(self):
        terminal = self._terminal_creada()
        self.client.delete(reverse('terminal-detail', args=[terminal.pk]))
        terminal.caja.refresh_from_db()
        self.assertEqual(terminal.caja.estado, 'CERRADA')
        self.assertEqual(terminal.caja.stock_billetes.count(), 2)

    def test_el_stock_de_una_terminal_activa_cuenta_como_disponible_y_el_de_una_inactiva_no(self):
        terminal = self._terminal_creada()
        self.assertEqual(
            services._stock_en_cajas_abiertas(self.usd.pk),
            {self.billete_100.pk: 3, self.billete_50.pk: 2},
        )
        self.client.patch(
            reverse('terminal-detail', args=[terminal.pk]),
            {'estado': Terminal.INACTIVA}, format='json',
        )
        self.assertEqual(services._stock_en_cajas_abiertas(self.usd.pk), {})
