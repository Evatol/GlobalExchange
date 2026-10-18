from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.divisas.models import Moneda

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

        respuesta = self.client.get(reverse('terminal_demo', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_409_CONFLICT)
        self.assertContains(respuesta, 'Terminal no operativa', status_code=409)


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

    def test_demo_de_terminal_activa_permite_iniciar(self):
        terminal = self._terminal_creada()

        respuesta = self.client.post(reverse('terminal_demo', args=[terminal.pk]))

        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        self.assertContains(respuesta, 'La simulación está lista para iniciar')
