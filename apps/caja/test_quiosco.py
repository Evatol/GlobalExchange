"""Tests de E4-193 (ingresar a la terminal) y E4-194 (operar en efectivo en la terminal)."""
from decimal import Decimal

from django.test import Client
from django.urls import reverse

from apps.transacciones.models import Transaccion
from apps.usuarios.models import Cliente

from . import services
from .models import MovimientoBillete, StockBillete, Terminal
from .test_cierre_movimientos import BaseCajaPresencialTests
from .test_sucursales import _login_con_rol, _usuario_negocio


class BaseQuioscoTests(BaseCajaPresencialTests):
    """El cliente VIP de la base, asociado a un usuario que se identifica en una terminal
    activa con billetes de guaraníes, dólares y euros (la caja del mostrador queda aparte)."""

    def setUp(self):
        super().setUp()
        self.terminal = services.crear_terminal(
            'Terminal Test', self.sucursal, Terminal.ACTIVA, self.carga_inicial()
        )
        self.login_cli = _login_con_rol('cli_kiosco', 'usuario_final')
        self.usuario = _usuario_negocio('cli_kiosco')
        self.usuario.clientes.add(self.cliente)
        self.web = Client()

    def url(self, nombre, *args):
        return reverse(nombre, args=[self.terminal.pk, *args])

    def identificar(self, login=None):
        """El cliente inicia sesión (Keycloak) y llega al ingreso de la terminal."""
        self.web.force_login(login or self.login_cli)
        return self.web.get(self.url('terminal_ingreso'))

    def stock_terminal(self):
        return dict(
            StockBillete.objects.filter(caja=self.terminal.caja).values_list('billete_id', 'cantidad')
        )

    def datos(self, **extra):
        datos = {'tipo': 'COMPRA', 'moneda_codigo': 'USD', 'cantidad': '100', 'accion': 'calcular'}
        datos.update(extra)
        return datos


class InicioDeLaTerminalTests(BaseQuioscoTests):
    def test_el_inicio_es_publico_y_muestra_cotizaciones_y_calculadora(self):
        respuesta = Client().get(self.url('terminal_inicio'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Cambio del Día')
        self.assertContains(respuesta, 'USD')
        self.assertContains(respuesta, 'Calculadora de Divisas')
        self.assertContains(respuesta, 'Identificarme para operar')

    def test_el_boton_de_identificarse_lleva_a_keycloak_y_vuelve_al_ingreso(self):
        respuesta = Client().get(self.url('terminal_inicio'))
        self.assertContains(respuesta, f'?next={self.url("terminal_ingreso")}')

    def test_se_puede_calcular_sin_identificarse(self):
        respuesta = Client().post(self.url('terminal_inicio'), {
            'moneda_codigo': 'USD', 'tipo_operacion': 'compra', 'cantidad': '100',
        })

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Resultado de la Simulación')
        self.assertEqual(Transaccion.objects.count(), 0)

    def test_una_terminal_que_no_esta_activa_no_deja_avanzar(self):
        for estado in (Terminal.INACTIVA, Terminal.MANTENIMIENTO):
            with self.subTest(estado=estado):
                self.terminal.estado = estado
                self.terminal.save(update_fields=['estado'])
                self.identificar()

                for nombre in ('terminal_inicio', 'terminal_ingreso', 'terminal_operar'):
                    respuesta = self.web.get(self.url(nombre))
                    self.assertContains(respuesta, 'Terminal no operativa', status_code=409)

    def test_una_terminal_de_una_sucursal_inactiva_no_deja_avanzar(self):
        self.sucursal.estado = False
        self.sucursal.save(update_fields=['estado'])
        respuesta = Client().get(self.url('terminal_inicio'))
        self.assertContains(respuesta, 'la sucursal está inactiva', status_code=409)

    def test_una_terminal_inexistente_da_404(self):
        self.assertEqual(Client().get(reverse('terminal_inicio', args=[9999])).status_code, 404)


class IngresoALaTerminalTests(BaseQuioscoTests):
    def test_sin_haberse_identificado_se_pide_el_login(self):
        for nombre in ('terminal_ingreso', 'terminal_cliente', 'terminal_operar'):
            with self.subTest(pantalla=nombre):
                respuesta = Client().get(self.url(nombre))
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn('/oidc/authenticate/', respuesta['Location'])

    def test_con_un_solo_cliente_se_va_directo_a_operar(self):
        respuesta = self.identificar()

        self.assertRedirects(respuesta, self.url('terminal_operar'))
        self.assertEqual(self.web.session['terminal_id'], self.terminal.pk)
        self.assertEqual(self.web.session['cliente_activo_id'], self.cliente.pk)

    def test_con_varios_clientes_primero_elige_uno(self):
        otro = Cliente.objects.create(
            nombre='Otro Cliente', documento='OTRO-1', tipo='FISICA', categoria=Cliente.CATEGORIA_VIP,
        )
        self.usuario.clientes.add(otro)

        self.assertRedirects(self.identificar(), self.url('terminal_cliente'))
        # No puede operar sin haber elegido.
        self.assertRedirects(self.web.get(self.url('terminal_operar')), self.url('terminal_cliente'))

        pantalla = self.web.get(self.url('terminal_cliente'))
        self.assertContains(pantalla, 'Cliente VIP')
        self.assertContains(pantalla, 'Otro Cliente')

        respuesta = self.web.post(self.url('terminal_cliente'), {'cliente': otro.pk})
        self.assertRedirects(respuesta, self.url('terminal_operar'))
        self.assertEqual(self.web.session['cliente_activo_id'], otro.pk)
        self.assertContains(self.web.get(self.url('terminal_operar')), 'Otro Cliente')

    def test_no_se_puede_elegir_un_cliente_que_no_es_del_usuario(self):
        ajeno = Cliente.objects.create(
            nombre='Cliente Ajeno', documento='AJENO-1', tipo='FISICA', categoria=Cliente.CATEGORIA_VIP,
        )
        otro = Cliente.objects.create(
            nombre='Otro Cliente', documento='OTRO-1', tipo='FISICA', categoria=Cliente.CATEGORIA_VIP,
        )
        self.usuario.clientes.add(otro)
        self.identificar()

        respuesta = self.web.post(self.url('terminal_cliente'), {'cliente': ajeno.pk})

        self.assertContains(respuesta, 'Elegí uno de los clientes de la lista')
        self.assertNotIn('cliente_activo_id', self.web.session)

    def test_un_usuario_sin_clientes_recibe_un_mensaje_claro(self):
        self.usuario.clientes.clear()

        self.assertRedirects(self.identificar(), self.url('terminal_cliente'))
        pantalla = self.web.get(self.url('terminal_cliente'))
        self.assertContains(pantalla, 'no está asociado a ningún cliente')
        self.assertNotContains(pantalla, 'dados de baja')
        self.assertRedirects(self.web.get(self.url('terminal_operar')), self.url('terminal_cliente'))

    def test_un_usuario_con_todos_sus_clientes_inactivos_recibe_un_mensaje_claro(self):
        Cliente.objects.filter(pk=self.cliente.pk).update(estado=False)

        self.identificar()

        self.assertContains(self.web.get(self.url('terminal_cliente')), 'dados de baja')

    def test_operar_sin_pasar_por_el_ingreso_manda_al_ingreso(self):
        self.web.force_login(self.login_cli)  # inició sesión, pero no en esta terminal
        self.assertRedirects(
            self.web.get(self.url('terminal_operar')), self.url('terminal_ingreso'),
            fetch_redirect_response=False,
        )

    def test_identificarse_en_otra_terminal_olvida_el_cliente_elegido(self):
        otra = services.crear_terminal('Otra Terminal', self.sucursal, Terminal.ACTIVA, self.carga_inicial())
        self.identificar()
        self.assertIn('cliente_activo_id', self.web.session)

        self.web.get(reverse('terminal_ingreso', args=[otra.pk]))

        self.assertEqual(self.web.session['terminal_id'], otra.pk)
        # Con un solo cliente se vuelve a fijar solo, pero se eligió de nuevo en la otra terminal.
        self.assertEqual(self.web.session['cliente_activo_id'], self.cliente.pk)


class OperarEnLaTerminalTests(BaseQuioscoTests):
    def setUp(self):
        super().setUp()
        self.identificar()

    def test_calcular_muestra_tasa_comision_total_y_billetes_sin_guardar_nada(self):
        antes = self.stock_terminal()

        respuesta = self.web.post(self.url('terminal_operar'), self.datos())

        self.assertContains(respuesta, 'Resumen de tu operación')
        self.assertContains(respuesta, 'Tasa')
        self.assertContains(respuesta, 'Comisión (1,50%)')
        self.assertContains(respuesta, 'Total a pagar')
        self.assertContains(respuesta, 'Ingresá estos billetes')
        self.assertContains(respuesta, 'La terminal te entrega')
        self.assertContains(respuesta, 'Confirmar operación')
        self.assertEqual(Transaccion.objects.count(), 0)
        self.assertEqual(self.stock_terminal(), antes)

    def test_confirmar_una_compra_registra_la_operacion_en_la_caja_de_la_terminal(self):
        antes_terminal, antes_mostrador = self.stock_terminal(), dict(
            StockBillete.objects.filter(caja=self.caja).values_list('billete_id', 'cantidad')
        )

        respuesta = self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar'))

        operacion = Transaccion.objects.get()
        self.assertRedirects(respuesta, self.url('terminal_comprobante', operacion.pk))
        self.assertEqual(
            (operacion.estado, operacion.modalidad, operacion.usuario, operacion.cliente),
            ('EXITOSA', 'TERMINAL', self.usuario, self.cliente),
        )
        self.assertEqual(operacion.metodo_pago.tipo, 'EFECTIVO')
        # Los billetes se movieron en la caja de la terminal, no en la del cajero.
        self.assertNotEqual(self.stock_terminal(), antes_terminal)
        self.assertEqual(
            dict(StockBillete.objects.filter(caja=self.caja).values_list('billete_id', 'cantidad')),
            antes_mostrador,
        )
        movimientos = MovimientoBillete.objects.filter(transaccion=operacion)
        self.assertTrue(movimientos.exists())
        self.assertEqual({m.caja_id for m in movimientos}, {self.terminal.caja_id})
        self.assertEqual({m.usuario_id for m in movimientos}, {self.usuario.pk})
        self.assertEqual({m.tipo for m in movimientos}, {'ENTRADA', 'SALIDA'})

    def test_una_operacion_en_la_terminal_genera_su_factura_como_presencial(self):
        self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar'))

        factura = Transaccion.objects.get().factura
        self.assertEqual(factura.payload['iIndPres'], '1')

    def test_se_puede_vender_y_cambiar_divisas(self):
        casos = (
            {'tipo': 'VENTA'},
            {'tipo': 'CAMBIO', 'moneda_codigo': 'USD', 'moneda_destino_codigo': 'EUR'},
        )
        for extra in casos:
            with self.subTest(extra=extra):
                respuesta = self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar', **extra))
                operacion = Transaccion.objects.order_by('-id').first()
                self.assertRedirects(respuesta, self.url('terminal_comprobante', operacion.pk))
                self.assertEqual((operacion.tipo, operacion.estado), (extra['tipo'], 'EXITOSA'))

    def test_el_comprobante_muestra_el_resultado_y_el_desglose_de_billetes(self):
        self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar'))
        operacion = Transaccion.objects.get()

        comprobante = self.web.get(self.url('terminal_comprobante', operacion.pk))

        self.assertContains(comprobante, 'Operación realizada')
        self.assertContains(comprobante, f'#{operacion.pk}')
        self.assertContains(comprobante, 'Billetes que ingresaste')
        self.assertContains(comprobante, 'Billetes que recibiste')
        self.assertContains(comprobante, 'USD')
        self.assertContains(comprobante, 'PYG')
        self.assertContains(comprobante, 'cli_kiosco@test.com')
        self.assertContains(comprobante, 'Nueva operación')
        self.assertContains(comprobante, 'Terminar y salir')

    def test_el_comprobante_es_solo_de_quien_hizo_la_operacion(self):
        self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar'))
        operacion = Transaccion.objects.get()

        otro_login = _login_con_rol('otro_cli', 'usuario_final')
        _usuario_negocio('otro_cli')
        otro = Client()
        otro.force_login(otro_login)
        otro.get(self.url('terminal_ingreso'))

        self.assertEqual(otro.get(self.url('terminal_comprobante', operacion.pk)).status_code, 404)

    def test_el_comprobante_no_muestra_operaciones_del_mostrador(self):
        operacion = self.operar()  # la atendió un cajero
        self.assertEqual(self.web.get(self.url('terminal_comprobante', operacion.pk)).status_code, 404)

    def test_no_se_puede_operar_con_un_cliente_dado_de_baja_despues_de_elegirlo(self):
        Cliente.objects.filter(pk=self.cliente.pk).update(estado=False)

        respuesta = self.web.post(self.url('terminal_operar'), self.datos(accion='confirmar'))

        self.assertRedirects(respuesta, self.url('terminal_cliente'))
        self.assertEqual(Transaccion.objects.count(), 0)

    def test_datos_invalidos_se_informan_sin_registrar_nada(self):
        for extra, mensaje in (
            ({'cantidad': '0'}, 'La cantidad debe ser mayor a 0'),
            ({'moneda_codigo': 'JPY'}, 'No hay cotización activa para JPY'),
            ({'tipo': 'CAMBIO', 'moneda_destino_codigo': ''}, 'Elegí la moneda que querés recibir'),
        ):
            with self.subTest(extra=extra):
                respuesta = self.web.post(self.url('terminal_operar'), self.datos(**extra))
                self.assertContains(respuesta, mensaje)
        self.assertEqual(Transaccion.objects.count(), 0)


class FallasAlOperarEnLaTerminalTests(BaseQuioscoTests):
    def operar_como(self, cliente, **extra):
        self.usuario.clientes.set([cliente])
        self.identificar()
        return self.web.post(self.url('terminal_operar'), self.datos(**extra))

    def test_el_limite_de_la_categoria_se_informa_al_calcular_y_no_deja_confirmar(self):
        minorista = Cliente.objects.create(
            nombre='Cliente Minorista', documento='MIN-1', tipo='FISICA',
            categoria=Cliente.CATEGORIA_MINORISTA,
        )

        respuesta = self.operar_como(minorista)  # 100 USD son más de 100.000 Gs

        self.assertContains(respuesta, 'supera el límite por operación')
        self.assertNotContains(respuesta, 'Confirmar operación')

    def test_confirmar_por_encima_del_limite_queda_fallida_y_no_mueve_billetes(self):
        minorista = Cliente.objects.create(
            nombre='Cliente Minorista', documento='MIN-1', tipo='FISICA',
            categoria=Cliente.CATEGORIA_MINORISTA,
        )
        antes = self.stock_terminal()

        respuesta = self.operar_como(minorista, accion='confirmar')

        fallida = Transaccion.objects.get()
        self.assertEqual((fallida.estado, fallida.modalidad), ('FALLIDA', 'TERMINAL'))
        self.assertIn('supera el límite', fallida.observacion)
        self.assertContains(respuesta, 'No se pudo completar la operación')
        self.assertContains(respuesta, f'operación #{fallida.pk}')
        self.assertEqual(self.stock_terminal(), antes)
        self.assertFalse(MovimientoBillete.objects.filter(transaccion=fallida).exists())

    def test_sin_billetes_suficientes_se_avisa_al_calcular(self):
        pocas = services.crear_terminal(
            'Terminal Casi Vacia', self.sucursal, Terminal.ACTIVA, {self.b[('USD', 100)].pk: 1},
        )
        self.terminal = pocas
        self.identificar()

        respuesta = self.web.post(self.url('terminal_operar'), self.datos(cantidad='1000'))

        self.assertContains(respuesta, 'La terminal no puede completar esta operación')
        self.assertContains(respuesta, 'No hay billetes suficientes de USD')
        self.assertNotContains(respuesta, 'Confirmar operación')

    def test_confirmar_sin_billetes_suficientes_queda_fallida_y_no_mueve_billetes(self):
        pocas = services.crear_terminal(
            'Terminal Casi Vacia', self.sucursal, Terminal.ACTIVA, {self.b[('USD', 100)].pk: 1},
        )
        self.terminal = pocas
        self.identificar()
        antes = self.stock_terminal()

        respuesta = self.web.post(self.url('terminal_operar'), self.datos(cantidad='1000', accion='confirmar'))

        fallida = Transaccion.objects.get()
        self.assertEqual(fallida.estado, 'FALLIDA')
        self.assertIn('No hay billetes suficientes de USD', fallida.observacion)
        self.assertContains(respuesta, 'No se pudo completar la operación')
        self.assertEqual(self.stock_terminal(), antes)

    def test_una_falla_no_impide_hacer_otra_operacion(self):
        pocas = services.crear_terminal(
            'Terminal Casi Vacia', self.sucursal, Terminal.ACTIVA,
            {self.b[('USD', 100)].pk: 2, self.b[('PYG', 100000)].pk: 5},
        )
        self.terminal = pocas
        self.identificar()
        self.web.post(self.url('terminal_operar'), self.datos(cantidad='1000', accion='confirmar'))

        respuesta = self.web.post(self.url('terminal_operar'), self.datos(cantidad='100', accion='confirmar'))

        exitosa = Transaccion.objects.get(estado='EXITOSA')
        self.assertRedirects(respuesta, self.url('terminal_comprobante', exitosa.pk))
        self.assertEqual(Transaccion.objects.filter(estado='FALLIDA').count(), 1)


class ServicioDeTerminalTests(BaseQuioscoTests):
    def test_el_cliente_tiene_que_ser_del_usuario_que_se_identifico(self):
        ajeno = Cliente.objects.create(
            nombre='Cliente Ajeno', documento='AJENO-1', tipo='FISICA', categoria=Cliente.CATEGORIA_VIP,
        )
        with self.assertRaisesMessage(Exception, 'no está asociado a tu usuario'):
            services.registrar_operacion_en_terminal(
                terminal=self.terminal, usuario=self.usuario, cliente=ajeno,
                tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
            )
        self.assertEqual(Transaccion.objects.count(), 0)

    def test_una_terminal_no_operativa_no_registra_ni_un_intento_fallido(self):
        self.terminal.estado = Terminal.MANTENIMIENTO
        self.terminal.save(update_fields=['estado'])
        with self.assertRaisesMessage(Exception, 'Terminal no operativa'):
            services.registrar_operacion_en_terminal(
                terminal=self.terminal, usuario=self.usuario, cliente=self.cliente,
                tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
            )
        self.assertEqual(Transaccion.objects.count(), 0)

    def test_el_mostrador_sigue_exigiendo_que_la_caja_sea_del_cajero(self):
        with self.assertRaisesMessage(Exception, 'no está asignada a este cajero'):
            services.registrar_operacion_presencial(
                caja=self.terminal.caja, usuario=self.cajero, cliente=self.cliente,
                tipo='COMPRA', moneda_codigo='USD', cantidad=Decimal('100'),
            )
