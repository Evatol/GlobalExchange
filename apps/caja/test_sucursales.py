from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.usuarios.models import Usuario

from .models import AsignacionCajero, Sucursal

User = get_user_model()


def _login_con_rol(username, rol):
    """Usuario de login (Django) con el grupo ``rol``, como lo deja la
    sincronización de roles desde Keycloak."""
    user = User.objects.create_user(username, password='x')
    grupo, _ = Group.objects.get_or_create(name=rol)
    user.groups.add(grupo)
    return user


def _usuario_negocio(username):
    return Usuario.objects.create(
        username=username,
        email=f'{username}@test.com',
        nombres='Test',
        apellidos='Test',
        telefono='0981000000',
        direccion='Asunción',
    )


def _cajero(username):
    """Cajero completo: login con grupo ``cajero`` + ``Usuario`` de negocio."""
    _login_con_rol(username, 'cajero')
    return _usuario_negocio(username)


class SucursalTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(_login_con_rol('admin1', 'administrador'))
        self.sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')

    def test_registrar_sucursal(self):
        r = self.client.post(
            reverse('sucursal-list'),
            {'nombre': 'Norte', 'direccion': 'Luque', 'estado': True},
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Sucursal.objects.count(), 2)

    def test_borrado_logico_desactiva_no_elimina(self):
        r = self.client.delete(reverse('sucursal-detail', args=[self.sucursal.id]))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.sucursal.refresh_from_db()
        self.assertFalse(self.sucursal.estado)

    def test_activar_sucursal(self):
        self.sucursal.desactivar()
        r = self.client.post(reverse('sucursal-activar', args=[self.sucursal.id]))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.sucursal.refresh_from_db()
        self.assertTrue(self.sucursal.estado)

    def test_no_administrador_no_accede(self):
        self.client.force_authenticate(_login_con_rol('final1', 'usuario_final'))
        r = self.client.get(reverse('sucursal-list'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class AsignacionCajeroTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(_login_con_rol('admin1', 'administrador'))
        self.sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')
        self.url = reverse('asignacioncajero-list')

    def _asignar(self, usuario):
        return self.client.post(
            self.url, {'sucursal': self.sucursal.id, 'usuario': usuario.id}
        )

    def test_asigna_hasta_dos_cajeros(self):
        self.assertEqual(self._asignar(_cajero('caj1')).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._asignar(_cajero('caj2')).status_code, status.HTTP_201_CREATED)

    def test_tercer_cajero_rechazado_con_mensaje_claro(self):
        self.assertEqual(self._asignar(_cajero('caj1')).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._asignar(_cajero('caj2')).status_code, status.HTTP_201_CREATED)
        r = self._asignar(_cajero('caj3'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tercero', str(r.data))
        activos = AsignacionCajero.objects.filter(sucursal=self.sucursal, estado=True)
        self.assertEqual(activos.count(),2)

    def test_asignacion_sin_enviar_estado_nace_activa(self):
        r = self._asignar(_cajero('caj1'))
        self.assertTrue(r.data['estado'])

    def test_usuario_sin_rol_cajero_rechazado(self):
        r = self._asignar(_usuario_negocio('sinrol'))
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('usuario', r.data)

    def test_desasignar_libera_un_lugar(self):
        primera = self._asignar(_cajero('caj1'))
        self._asignar(_cajero('caj2'))
        r = self.client.delete(
            reverse('asignacioncajero-detail', args=[primera.data['id']])
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(self._asignar(_cajero('caj3')).status_code, status.HTTP_201_CREATED)

    def test_reasignar_respeta_el_maximo(self):
        primera = self._asignar(_cajero('caj1'))
        self._asignar(_cajero('caj2'))
        self.client.delete(reverse('asignacioncajero-detail', args=[primera.data['id']]))
        self._asignar(_cajero('caj3'))
        r = self.client.post(
            reverse('asignacioncajero-activar', args=[primera.data['id']])
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class AccesoCajeroTests(APITestCase):
    def test_cajero_recibe_403_fuera_del_modulo_de_caja(self):
        self.client.force_login(_login_con_rol('caj1', 'cajero'))
        r = self.client.get(reverse('historial_transacciones'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_administrador_no_se_restringe(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))
        r = self.client.get(reverse('historial_transacciones'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)

class PantallaSucursalesTests(APITestCase):
    def setUp(self):
        self.client.force_login(_login_con_rol('admin1', 'administrador'))
        self.sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')

    def _asignar(self, usuario):
        return self.client.post(
            reverse('gestion_sucursales'),
            {'accion': 'asignar', 'sucursal': self.sucursal.id, 'usuario': usuario.id},
        )

    def test_admin_ve_la_pantalla(self):
        r = self.client.get(reverse('gestion_sucursales'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertContains(r, 'Central')

    def test_no_administrador_recibe_403(self):
        self.client.force_login(_login_con_rol('final1', 'usuario_final'))
        r = self.client.get(reverse('gestion_sucursales'))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_crear_sucursal_desde_la_pantalla_nace_activa(self):
        r = self.client.post(
            reverse('gestion_sucursales'), {'nombre': 'Norte', 'direccion': 'Luque'}
        )
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        self.assertTrue(Sucursal.objects.get(nombre='Norte').estado)

    def test_tercer_cajero_muestra_el_error_en_pantalla(self):
        self._asignar(_cajero('caj1'))
        self._asignar(_cajero('caj2'))
        r = self._asignar(_cajero('caj3'))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertContains(r, 'tercero')
        activos = AsignacionCajero.objects.filter(sucursal=self.sucursal, estado=True)
        self.assertEqual(activos.count(), 2)

    def test_quitar_y_volver_a_asignar_un_cajero(self):
        caj = _cajero('caj1')
        self._asignar(caj)
        asignacion = AsignacionCajero.objects.get(usuario=caj)
        r = self.client.post(reverse('asignacion_cajero_desasignar', args=[asignacion.id]))
        self.assertEqual(r.status_code, status.HTTP_302_FOUND)
        asignacion.refresh_from_db()
        self.assertFalse(asignacion.estado)

        self._asignar(caj)
        asignacion.refresh_from_db()
        self.assertTrue(asignacion.estado)
        self.assertEqual(AsignacionCajero.objects.filter(usuario=caj).count(), 1)