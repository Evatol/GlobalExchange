"""Tests de E4-100 (balance y cierre de caja) y E4-101 (registro automático de
movimientos de billetes en la operación presencial)."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.divisas.models import Moneda, TasaCambio
from apps.transacciones.models import MetodoPago, Transaccion
from apps.usuarios.models import Cliente

from . import services
from .models import (
    Arqueo, AsignacionCajero, Billete, Caja, CierreCaja, MovimientoBillete,
    StockBillete, Sucursal,
)
from .test_sucursales import _cajero, _login_con_rol, _usuario_negocio

User = get_user_model()

PYG = [2000, 5000, 10000, 20000, 50000, 100000]
USD = [1, 5, 10, 20, 50, 100]
EUR = [5, 10, 20, 50, 100]


class BaseCajaPresencialTests(APITestCase):
    """Una caja abierta con billetes de guaraníes, dólares y euros, un cliente
    VIP (sin límite por operación) y cotizaciones de USD y EUR."""

    def setUp(self):
        self.pyg = Moneda.objects.create(codigo='PYG', nombre='Guaraní', simbolo='₲')
        self.usd = Moneda.objects.create(codigo='USD', nombre='Dólar', simbolo='$')
        self.eur = Moneda.objects.create(codigo='EUR', nombre='Euro', simbolo='€')
        self.b = {}
        for moneda, denominaciones in ((self.pyg, PYG), (self.usd, USD), (self.eur, EUR)):
            for d in denominaciones:
                self.b[(moneda.codigo, d)] = Billete.objects.create(
                    moneda=moneda, denominacion=Decimal(d)
                )
        TasaCambio.objects.create(
            moneda=self.usd, tasa_compra=Decimal('7300'), tasa_venta=Decimal('7400'), origen='x',
        )
        TasaCambio.objects.create(
            moneda=self.eur, tasa_compra=Decimal('7900'), tasa_venta=Decimal('8050'), origen='x',
        )
        MetodoPago.objects.create(nombre='Efectivo', tipo='EFECTIVO')
        self.cliente = Cliente.objects.create(
            nombre='Cliente VIP', documento='VIP-1', tipo='FISICA', categoria=Cliente.CATEGORIA_VIP,
            preferencia_tipo_cambio=Cliente.PREFERENCIA_ESTANDAR,
        )

        self.sucursal = Sucursal.objects.create(nombre='Central', direccion='Asunción')
        self.cajero = _cajero('caj_pres')
        self.login = User.objects.get(username='caj_pres')
        AsignacionCajero.objects.create(sucursal=self.sucursal, usuario=self.cajero)
        self.caja = Caja.objects.create(
            sucursal=self.sucursal, cajero=self.cajero, saldo_inicial=0, saldo_actual=0
        )
        services.abrir_caja(self.caja, self.cajero, self.carga_inicial())
        self.caja.refresh_from_db()

    def carga_inicial(self):
        carga = {self.b[('PYG', d)].id: 10 for d in PYG}
        carga.update({self.b[('USD', d)].id: 10 for d in USD})
        carga.update({self.b[('EUR', d)].id: 10 for d in EUR})
        return carga

    def cantidad(self, moneda, denominacion):
        fila = StockBillete.objects.filter(caja=self.caja, billete=self.b[(moneda, denominacion)]).first()
        return fila.cantidad if fila else 0

    def operar(self, **kw):
        datos = dict(
            caja=self.caja, usuario=self.cajero, cliente=self.cliente,
            tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
        )
        datos.update(kw)
        return services.registrar_operacion_presencial(**datos)


class DesgloseDeMontoTests(BaseCajaPresencialTests):
    """El sistema arma solo los billetes de una operación."""

    def test_usa_primero_las_denominaciones_mas_grandes(self):
        desglose = services.desglose_de_monto(self.pyg.id, Decimal('170000'))
        self.assertEqual(desglose, {
            self.b[('PYG', 100000)].id: 1, self.b[('PYG', 50000)].id: 1, self.b[('PYG', 20000)].id: 1,
        })

    def test_los_centavos_se_redondean_al_billete_minimo(self):
        # 96.681: 50k + 20k + 20k + 5k = 95.000 y sobran 1.681 (>= 1.000) -> un billete de 2.000
        desglose = services.desglose_de_monto(self.pyg.id, Decimal('96681'))
        total = sum(Decimal(self.b_por_id(i)) * n for i, n in desglose.items())
        self.assertEqual(total, Decimal('97000'))
        self.assertLessEqual(abs(total - Decimal('96681')), Decimal('1000'))  # media denominación mínima

    def b_por_id(self, billete_id):
        return Billete.objects.get(pk=billete_id).denominacion

    def test_un_monto_exacto_no_agrega_billetes_de_mas(self):
        desglose = services.desglose_de_monto(self.usd.id, Decimal('135'))
        self.assertEqual(
            sum(self.b_por_id(i) * n for i, n in desglose.items()), Decimal('135')
        )

    def test_al_entregar_respeta_el_stock(self):
        # Solo hay 2 billetes de 100: 250 se cubre con 2x100 + 1x50
        disponible = {self.b[('USD', 100)].id: 2, self.b[('USD', 50)].id: 5}
        desglose = services.desglose_de_monto(self.usd.id, Decimal('250'), disponible)
        self.assertEqual(desglose, {self.b[('USD', 100)].id: 2, self.b[('USD', 50)].id: 1})

    def test_sin_stock_suficiente_falla_con_un_mensaje(self):
        disponible = {self.b[('USD', 100)].id: 1}
        with self.assertRaisesMessage(ValidationError, 'No hay billetes suficientes de USD'):
            services.desglose_de_monto(self.usd.id, Decimal('250'), disponible)

    def test_moneda_sin_denominaciones(self):
        brl = Moneda.objects.create(codigo='BRL', nombre='Real', simbolo='R$')
        with self.assertRaisesMessage(ValidationError, 'No hay denominaciones cargadas para BRL'):
            services.desglose_de_monto(brl.id, Decimal('10'))


class RegistroAutomaticoTests(BaseCajaPresencialTests):
    """E4-101: al confirmar una operación presencial, los movimientos de
    billetes y el stock se registran solos."""

    def test_compra_la_caja_recibe_guaranies_y_entrega_dolares(self):
        tx = self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        # 100 USD x 7.400 = 740.000 + 1,5% = 751.100 guaraníes que recibe la caja
        self.assertEqual(tx.estado, 'EXITOSA')
        self.assertEqual(tx.modalidad, 'PRESENCIAL')
        self.assertEqual(tx.monto_total, Decimal('751100.00'))
        entrada = MovimientoBillete.objects.filter(transaccion=tx, tipo='ENTRADA')
        salida = MovimientoBillete.objects.filter(transaccion=tx, tipo='SALIDA')
        self.assertEqual({m.billete.moneda.codigo for m in entrada}, {'PYG'})
        self.assertEqual({m.billete.moneda.codigo for m in salida}, {'USD'})
        self.assertEqual(self.cantidad('USD', 100), 9)     # entregó 1 billete de 100
        self.assertEqual(sum(m.billete.denominacion * m.cantidad for m in salida), Decimal('100'))
        self.assertTrue(all(m.usuario == self.cajero for m in entrada | salida))

    def test_venta_la_caja_recibe_dolares_y_entrega_guaranies(self):
        tx = self.operar(tipo='VENTA', moneda_codigo='USD', cantidad=Decimal('100'))
        self.assertEqual(self.cantidad('USD', 100), 11)
        entregados = MovimientoBillete.objects.filter(transaccion=tx, tipo='SALIDA')
        self.assertEqual({m.billete.moneda.codigo for m in entregados}, {'PYG'})
        # 100 x 7.300 = 730.000 - 1,5% = 719.050 -> se entrega lo más cercano en billetes
        entregado = sum(m.billete.denominacion * m.cantidad for m in entregados)
        self.assertLessEqual(abs(entregado - tx.monto_total), Decimal('1000'))

    def test_cambio_entre_divisas_mueve_dos_monedas(self):
        tx = self.operar(
            tipo='CAMBIO', moneda_codigo='USD', moneda_destino_codigo='EUR', cantidad=Decimal('100'),
        )
        self.assertEqual(tx.tipo, 'CAMBIO')
        monedas = {
            (m.tipo, m.billete.moneda.codigo) for m in MovimientoBillete.objects.filter(transaccion=tx)
        }
        self.assertEqual(monedas, {('ENTRADA', 'USD'), ('SALIDA', 'EUR')})

    def test_el_balance_de_billetes_coincide_con_la_operacion(self):
        tx = self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('50'))
        balance = {f['moneda']: f for f in services.balance_caja(self.caja)['monedas']}
        self.assertEqual(balance['USD']['entregado'], Decimal('50'))
        self.assertEqual(balance['USD']['recibido'], Decimal('0'))
        self.assertGreaterEqual(balance['PYG']['recibido'], tx.monto_total - Decimal('1000'))

    def test_si_algo_falla_no_queda_nada_guardado(self):
        # Se pide más de lo que hay de dólares: 10 x 100 + ... = 1.940 en la caja
        antes = (Transaccion.objects.count(), MovimientoBillete.objects.count())
        stock = self.cantidad('PYG', 100000)
        with self.assertRaises(ValidationError):
            self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('5000'))
        self.assertEqual((Transaccion.objects.count(), MovimientoBillete.objects.count()), antes)
        self.assertEqual(self.cantidad('PYG', 100000), stock)

    def test_con_billetes_indicados_se_respeta_lo_que_cargo_el_cajero(self):
        """Si el cliente pagó con otros billetes, el cajero los indica y no se
        usa el desglose automático."""
        recibidos = {self.b[('PYG', 50000)].id: 15, self.b[('PYG', 10000)].id: 0}  # 750.000
        recibidos[self.b[('PYG', 2000)].id] = 1                                    # +2.000 = 752.000
        entregados = {self.b[('USD', 20)].id: 5}                                    # 100 USD
        tx = self.operar(
            tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
            recibidos=recibidos, entregados=entregados,
        )
        self.assertEqual(self.cantidad('PYG', 50000), 25)
        self.assertEqual(self.cantidad('USD', 20), 5)
        self.assertEqual(MovimientoBillete.objects.filter(transaccion=tx, tipo='SALIDA').count(), 1)

    def test_billetes_que_no_cierran_con_la_operacion_se_rechazan(self):
        with self.assertRaisesMessage(ValidationError, 'no coinciden con la operación'):
            self.operar(
                tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
                recibidos={self.b[('PYG', 2000)].id: 1}, entregados={self.b[('USD', 100)].id: 1},
            )

    def test_la_operacion_aplica_el_limite_del_cliente(self):
        self.cliente.actualizar_categoria(Cliente.CATEGORIA_MINORISTA)  # 100.000 por operación
        with self.assertRaisesMessage(ValidationError, 'supera el límite por operación'):
            self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        self.assertFalse(Transaccion.objects.exists())

    def test_la_caja_tiene_que_ser_del_cajero(self):
        otro = _cajero('otro_caj')
        with self.assertRaisesMessage(ValidationError, 'no está asignada a este cajero'):
            self.operar(usuario=otro)


class BalanceYCierreTests(BaseCajaPresencialTests):
    """E4-100: balance de la sesión y cierre de caja."""

    def test_balance_de_una_caja_sin_operaciones(self):
        balance = services.balance_caja(self.caja)
        self.assertEqual(balance['operaciones'], 0)
        usd = next(f for f in balance['monedas'] if f['moneda'] == 'USD')
        self.assertEqual(usd['carga_inicial'], Decimal('1860'))  # 10 x (1+5+10+20+50+100)
        self.assertEqual(usd['saldo_al_abrir'], Decimal('0'))
        self.assertEqual(usd['saldo_actual'], Decimal('1860'))

    def test_el_balance_siempre_cierra(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        self.operar(tipo='VENTA', moneda_codigo='EUR', cantidad=Decimal('30'))
        balance = services.balance_caja(self.caja)
        self.assertEqual(balance['operaciones'], 2)
        for f in balance['monedas']:
            self.assertEqual(
                f['saldo_al_abrir'] + f['carga_inicial'] + f['recibido'] - f['entregado'],
                f['saldo_actual'], f['moneda'],
            )

    def test_cerrar_la_caja_guarda_el_balance_de_la_sesion(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        cierre = services.cerrar_caja(self.caja, self.cajero)
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'CERRADA')
        self.assertIsNotNone(self.caja.fecha_cierre)
        self.assertEqual((cierre.operaciones, cierre.cerrado_por, cierre.cajero), (1, self.cajero, self.cajero))
        usd = cierre.detalles.get(moneda=self.usd)
        self.assertEqual(
            (usd.saldo_inicial, usd.recibido, usd.entregado, usd.saldo_final),
            (Decimal('1860'), Decimal('0'), Decimal('100'), Decimal('1760')),
        )
        self.assertIsNone(usd.total_contado)  # no se contó

    def test_al_cerrar_se_puede_contar_una_moneda_y_queda_la_diferencia(self):
        contados = {str(self.usd.id): {str(self.b[('USD', 100)].id): 9}}   # faltan 10 billetes de 100 en realidad
        contados[str(self.usd.id)].update({str(self.b[(('USD'), d)].id): 10 for d in (1, 5, 10, 20, 50)})
        cierre = services.cerrar_caja(self.caja, self.cajero, contados)
        usd = cierre.detalles.get(moneda=self.usd)
        self.assertEqual(usd.total_contado, Decimal('1760'))
        self.assertEqual(usd.diferencia, Decimal('-100'))
        self.assertEqual(cierre.detalles.get(moneda=self.eur).diferencia, None)  # esa no se contó
        self.assertEqual(Arqueo.objects.filter(caja=self.caja, moneda=self.usd).count(), 1)

    def test_una_diferencia_no_impide_cerrar(self):
        cierre = services.cerrar_caja(self.caja, self.cajero, {str(self.usd.id): {}})
        self.assertEqual(cierre.detalles.get(moneda=self.usd).total_contado, Decimal('0'))
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'CERRADA')

    def test_no_se_cierra_dos_veces_ni_se_opera_con_la_caja_cerrada(self):
        services.cerrar_caja(self.caja, self.cajero)
        with self.assertRaisesMessage(ValidationError, 'no está abierta'):
            services.cerrar_caja(self.caja, self.cajero)
        with self.assertRaises(ValidationError):
            self.operar()
        self.assertEqual(CierreCaja.objects.count(), 1)

    def test_el_stock_queda_como_remanente_y_se_reabre_con_lo_que_quedo(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        services.cerrar_caja(self.caja, self.cajero)
        stock_usd = self.cantidad('USD', 100)
        caja = services.abrir_caja(self.caja, self.cajero, {self.b[('USD', 5)].id: 2})
        self.assertEqual(self.cantidad('USD', 100), stock_usd)  # el cierre no vació la caja
        balance = {f['moneda']: f for f in services.balance_caja(caja)['monedas']}
        self.assertEqual(balance['USD']['saldo_al_abrir'], Decimal('1760'))  # lo que había
        self.assertEqual(balance['USD']['carga_inicial'], Decimal('10'))     # 2 x 5 nuevos
        self.assertEqual(balance['USD']['recibido'], Decimal('0'))           # la sesión anterior no cuenta
        self.assertEqual(services.balance_caja(caja)['operaciones'], 0)

    def test_moneda_invalida_en_el_cierre(self):
        with self.assertRaisesMessage(ValidationError, 'Moneda inexistente'):
            services.cerrar_caja(self.caja, self.cajero, {'abc': {}})
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'ABIERTA')


class ApiCierreMovimientosTests(BaseCajaPresencialTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.login)
        self.admin = _login_con_rol('admin_cm', 'administrador')
        _usuario_negocio('admin_cm')  # el Usuario de negocio que crea el login OIDC

    def test_previsualizar_sugiere_los_billetes(self):
        r = self.client.post(reverse('operacion_presencial_calcular'), {
            'documento': 'VIP-1', 'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '100',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        billetes = r.data['billetes']
        self.assertIsNone(billetes['advertencia'])
        self.assertEqual({b['moneda'] for b in billetes['recibir']}, {'PYG'})
        self.assertEqual([b['denominacion'] for b in billetes['entregar']], [Decimal('100')])

    def test_previsualizar_avisa_si_la_caja_no_tiene_stock(self):
        r = self.client.post(reverse('operacion_presencial_calcular'), {
            'documento': 'VIP-1', 'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '5000',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('No hay billetes suficientes', r.data['billetes']['advertencia'])

    def test_operar_sin_billetes_los_registra_solo(self):
        r = self.client.post(reverse('operacion_presencial'), {
            'documento': 'VIP-1', 'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '100',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(MovimientoBillete.objects.filter(transaccion=r.data['transaccion_id']).count() > 0, True)

    def test_operar_con_billetes_vacios_sigue_exigiendo_al_menos_uno(self):
        """``{}`` no es "calculalo": es "no hubo billetes", y se rechaza como antes."""
        r = self.client.post(reverse('operacion_presencial'), {
            'documento': 'VIP-1', 'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '100',
            'recibidos': {}, 'entregados': {},
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_mi_balance(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        r = self.client.get(reverse('mi_balance'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['operaciones'], 1)
        self.assertEqual({f['moneda'] for f in r.data['monedas']}, {'PYG', 'USD', 'EUR'})

    def test_el_cajero_cierra_su_caja_por_api(self):
        r = self.client.post(reverse('mi_cierre'), {}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data['detalles']), 3)
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'CERRADA')
        # sin caja abierta ya no puede
        self.assertEqual(self.client.post(reverse('mi_cierre'), {}, format='json').status_code, 400)

    def test_el_administrador_cierra_cualquier_caja_y_ve_su_balance(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('caja-balance', args=[self.caja.pk])).status_code, 200)
        r = self.client.post(reverse('caja-cerrar', args=[self.caja.pk]), {}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(CierreCaja.objects.get().cerrado_por.username, 'admin_cm')

    def test_el_cajero_no_cierra_cajas_ajenas_ni_usa_las_rutas_del_administrador(self):
        self.assertEqual(self.client.post(reverse('caja-cerrar', args=[self.caja.pk]), {}).status_code, 403)

    def test_movimientos_el_cajero_ve_solo_los_de_su_caja(self):
        tx = self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        # otra caja con sus propios movimientos
        otro = _cajero('otro_mov')
        AsignacionCajero.objects.create(sucursal=self.sucursal, usuario=otro)
        caja2 = Caja.objects.create(sucursal=self.sucursal, cajero=otro, saldo_inicial=0, saldo_actual=0)
        services.abrir_caja(caja2, otro, {self.b[('USD', 100)].id: 3})

        r = self.client.get(reverse('movimientobillete-list'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(m['caja'] == self.caja.pk for m in r.data['results']))

        r = self.client.get(reverse('movimientobillete-list'), {'transaccion': tx.pk})
        self.assertGreater(r.data['count'], 0)
        self.assertTrue(all(m['transaccion'] == tx.pk for m in r.data['results']))

        self.client.force_login(self.admin)
        cajas = {m['caja'] for m in self.client.get(reverse('movimientobillete-list')).data['results']}
        self.assertEqual(cajas, {self.caja.pk, caja2.pk})

    def test_movimientos_filtros(self):
        self.operar(tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'))
        r = self.client.get(reverse('movimientobillete-list'), {'tipo': 'SALIDA', 'moneda': self.usd.pk})
        self.assertGreater(r.data['count'], 0)
        self.assertTrue(all(m['tipo'] == 'SALIDA' and m['moneda_codigo'] == 'USD' for m in r.data['results']))
        r = self.client.get(reverse('movimientobillete-list'), {'fecha_desde': '2999-01-01'})
        self.assertEqual(r.data['count'], 0)

    def test_historial_de_cierres(self):
        services.cerrar_caja(self.caja, self.cajero)
        r = self.client.get(reverse('cierrecaja-list'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(len(r.data['results'][0]['detalles']), 3)

    def test_usuario_final_no_ve_movimientos_ni_cierres(self):
        self.client.force_login(_login_con_rol('final_cm', 'usuario_final'))
        self.assertEqual(self.client.get(reverse('movimientobillete-list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('cierrecaja-list')).status_code, 403)


class PantallasMostradorYCierreTests(BaseCajaPresencialTests):
    """Pantallas del cajero (mostrador, Mi Caja, cierre) y del administrador."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.login)
        self.admin = _login_con_rol('admin_pant', 'administrador')
        _usuario_negocio('admin_pant')

    def _datos(self, **extra):
        datos = {
            'documento': 'VIP-1', 'tipo': 'COMPRA', 'moneda_codigo': 'USD',
            'cantidad': '100', 'accion': 'calcular',
        }
        datos.update(extra)
        return datos

    def test_el_mostrador_calcula_y_muestra_los_billetes_que_arma_el_sistema(self):
        r = self.client.post(reverse('mostrador'), self._datos())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'La caja recibe')
        self.assertContains(r, 'La caja entrega')
        self.assertContains(r, 'Confirmar operación')
        self.assertContains(r, 'se registran solos')
        self.assertFalse(Transaccion.objects.exists())  # calcular no guarda nada

    def test_confirmar_registra_la_operacion_y_los_movimientos_solos(self):
        r = self.client.post(reverse('mostrador'), self._datos(accion='confirmar'), follow=True)
        self.assertRedirects(r, reverse('mi_caja'))
        self.assertContains(r, 'registraron automáticamente')
        tx = Transaccion.objects.get()
        self.assertEqual((tx.estado, tx.modalidad), ('EXITOSA', 'PRESENCIAL'))
        self.assertGreater(MovimientoBillete.objects.filter(transaccion=tx).count(), 0)
        # y se ven en Mi Caja, junto al balance
        self.assertContains(r, f'#{tx.pk}')
        self.assertContains(r, 'Balance de hoy')

    def test_cliente_inexistente(self):
        r = self.client.post(reverse('mostrador'), self._datos(documento='NO-EXISTE'))
        self.assertContains(r, 'No existe un cliente con ese documento')

    def test_cambio_pide_la_moneda_de_destino(self):
        r = self.client.post(reverse('mostrador'), self._datos(tipo='CAMBIO'))
        self.assertContains(r, 'Elegí la moneda que querés recibir')

    def test_cambio_entre_divisas_desde_el_mostrador(self):
        r = self.client.post(
            reverse('mostrador'), self._datos(tipo='CAMBIO', moneda_destino_codigo='EUR', accion='confirmar'),
            follow=True,
        )
        self.assertContains(r, 'confirmada')
        self.assertEqual(Transaccion.objects.get().tipo, 'CAMBIO')

    def test_sin_stock_avisa_antes_de_confirmar(self):
        r = self.client.post(reverse('mostrador'), self._datos(cantidad='5000'))
        self.assertContains(r, 'No hay billetes suficientes')
        self.assertNotContains(r, 'Confirmar operación')

    def test_confirmar_sin_stock_no_deja_nada_guardado(self):
        r = self.client.post(reverse('mostrador'), self._datos(cantidad='5000', accion='confirmar'))
        self.assertContains(r, 'No hay billetes suficientes')
        self.assertFalse(Transaccion.objects.exists())

    def test_sin_caja_abierta_el_mostrador_avisa(self):
        services.cerrar_caja(self.caja, self.cajero)
        r = self.client.get(reverse('mostrador'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'No tenés una caja abierta')

    def test_solo_el_cajero_entra_al_mostrador(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('mostrador')).status_code, 403)
        self.client.force_login(_login_con_rol('final_pant', 'usuario_final'))
        self.assertEqual(self.client.get(reverse('mostrador')).status_code, 403)

    def test_mi_caja_muestra_el_balance_y_los_botones(self):
        self.client.post(reverse('mostrador'), self._datos(accion='confirmar'))
        r = self.client.get(reverse('mi_caja'))
        for texto in ('Balance de hoy', 'Atender cliente', 'Cerrar caja', 'Últimos movimientos de billetes',
                      'carga inicial', '1 operación'):
            self.assertContains(r, texto)

    def test_cierre_sin_contar(self):
        r = self.client.post(reverse('caja_cerrar'), {}, follow=True)
        self.assertRedirects(r, reverse('mi_caja'))
        self.assertContains(r, 'cerrada')
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'CERRADA')
        # sin caja abierta, Mi Caja muestra el último cierre
        self.assertContains(r, 'Tu último cierre')
        self.assertContains(r, 'sin contar')

    def test_cierre_contando_una_moneda_con_diferencia(self):
        usd = {f'contado_{self.b[("USD", d)].id}': (9 if d == 100 else 10) for d in USD}
        r = self.client.post(reverse('caja_cerrar'), usd, follow=True)
        self.assertContains(r, 'Con diferencia en: USD')
        cierre = CierreCaja.objects.get()
        self.assertEqual(cierre.detalles.get(moneda=self.usd).diferencia, Decimal('-100'))
        self.assertIsNone(cierre.detalles.get(moneda=self.eur).diferencia)  # EUR sin contar

    def test_cierre_con_texto_en_las_cantidades(self):
        r = self.client.post(reverse('caja_cerrar'), {f'contado_{self.b[("USD", 100)].id}': 'abc'})
        self.assertContains(r, 'solo números enteros')
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'ABIERTA')

    def test_el_cierre_muestra_el_balance_antes_de_cerrar(self):
        r = self.client.get(reverse('caja_cerrar'))
        self.assertContains(r, 'Balance de hoy')
        self.assertContains(r, 'Contar los billetes (opcional)')

    def test_el_administrador_ve_el_balance_y_cierra_la_caja(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('caja_balance', args=[self.caja.pk]))
        self.assertContains(r, 'Balance de la sesión actual')
        self.assertContains(r, 'Cerrar caja')
        r = self.client.post(reverse('caja_cerrar_admin', args=[self.caja.pk]), follow=True)
        self.assertContains(r, 'cerrada')
        self.assertContains(r, 'Historial de cierres')
        self.assertContains(r, 'Cierre #')
        self.assertEqual(CierreCaja.objects.get().cerrado_por.username, 'admin_pant')

    def test_el_listado_de_cajas_enlaza_al_balance(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('gestion_cajas')), reverse('caja_balance', args=[self.caja.pk]))

    def test_el_cajero_no_ve_el_balance_del_administrador_ni_cierra_por_esa_via(self):
        self.assertEqual(self.client.get(reverse('caja_balance', args=[self.caja.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('caja_cerrar_admin', args=[self.caja.pk])).status_code, 403)
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'ABIERTA')

    def test_cerrar_por_get_no_cierra(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('caja_cerrar_admin', args=[self.caja.pk])).status_code, 405)
        self.caja.refresh_from_db()
        self.assertEqual(self.caja.estado, 'ABIERTA')

    def test_el_menu_del_cajero_tiene_el_mostrador(self):
        r = self.client.get(reverse('menu_principal'))
        self.assertContains(r, reverse('mostrador'))
