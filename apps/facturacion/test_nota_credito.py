"""Tests de E4-191: al anular una operación en efectivo se anula su factura con una nota de
crédito, y la emisión, la descarga y la anulación quedan en una auditoría inalterable."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from reportlab import rl_config

from apps.caja import services as caja
from apps.caja.models import StockBillete
from apps.caja.test_cierre_movimientos import BaseCajaPresencialTests
from apps.caja.test_sucursales import _login_con_rol, _usuario_negocio
from apps.facturacion import emision
from apps.facturacion.models import EventoFactura, Factura, NotaCredito, SecuenciaFactura
from apps.facturacion.services import generar_pdf, generar_pdf_nota_credito
from apps.transacciones.models import Transaccion

User = get_user_model()


class BaseNotaCreditoTests(BaseCajaPresencialTests):
    """Una caja abierta con billetes, un cliente VIP y un cajero (de ``caja``)."""

    def operar_con_factura(self, **kw):
        """Una operación en efectivo cuya factura ya se envió y quedó emitida."""
        with self.captureOnCommitCallbacks(execute=True):
            operacion = self.operar(**kw)
        return operacion, Factura.objects.get(transaccion=operacion)

    def anular(self, operacion, ejecutar_envio=True):
        """El cajero anula la operación desde su caja."""
        with self.captureOnCommitCallbacks(execute=ejecutar_envio):
            return caja.anular_operacion_en_efectivo(self.caja, operacion.pk)

    def stock(self):
        return dict(StockBillete.objects.filter(caja=self.caja).values_list('billete_id', 'cantidad'))


class AnularLaFacturaTests(BaseNotaCreditoTests):
    def test_anular_la_operacion_anula_la_factura_y_emite_su_nota_de_credito(self):
        operacion, factura = self.operar_con_factura()
        self.assertEqual(factura.estado, Factura.EMITIDA)

        self.anular(operacion)

        factura.refresh_from_db()
        operacion.refresh_from_db()
        nota = NotaCredito.objects.get(factura=factura)
        self.assertEqual((operacion.estado, factura.estado), ('ANULADA', Factura.ANULADA))
        self.assertEqual(nota.estado, NotaCredito.EMITIDA)
        self.assertEqual(nota.monto, factura.monto)  # por el total
        self.assertEqual(nota.numero, '001-001-0000001')
        self.assertRegex(nota.cdc, r'^\d{44}$')
        self.assertEqual(nota.proveedor, 'SIMULADO')
        self.assertIsNotNone(nota.fecha_emision)

    def test_la_nota_referencia_la_factura_y_lleva_su_mismo_receptor_e_items(self):
        operacion, factura = self.operar_con_factura()
        self.anular(operacion)
        documento = NotaCredito.objects.get().payload

        self.assertEqual(documento['iTiDE'], '5')  # nota de crédito electrónica
        self.assertEqual(documento['dNumDoc'], '0000001')
        self.assertEqual(documento['iMotEmi'], '2')
        asociado = documento['gCamDEAsoc'][0]
        self.assertEqual((asociado['iTipDocAso'], asociado['dCdCDERef']), ('1', factura.cdc))
        self.assertEqual(documento['dNomRec'], factura.payload['dNomRec'])
        self.assertEqual(documento['dEmailRec'], factura.payload['dEmailRec'])
        self.assertEqual(documento['gCamItem'], factura.payload['gCamItem'])
        self.assertIn(factura.numero, documento['dInfAdic'])
        for campo in emision.CAMPOS_SOLO_DE_FACTURA:  # lo propio de la venta no va
            self.assertNotIn(campo, documento)

    def test_las_notas_tienen_su_propia_numeracion(self):
        _, f1 = self.operar_con_factura(cantidad=Decimal('10'))
        o2, f2 = self.operar_con_factura(cantidad=Decimal('20'))
        o3, f3 = self.operar_con_factura(cantidad=Decimal('30'))
        self.assertEqual([f1.numero, f2.numero, f3.numero],
                         ['001-001-0000001', '001-001-0000002', '001-001-0000003'])
        self.anular(o3)
        self.anular(o2)
        # la primera nota es la 1 aunque se anule la factura 3: no sigue la numeración de facturas
        self.assertEqual(NotaCredito.objects.get(factura=f3).numero, '001-001-0000001')
        self.assertEqual(NotaCredito.objects.get(factura=f2).numero, '001-001-0000002')
        self.assertEqual(SecuenciaFactura.objects.get(documento='FACTURA').ultimo_numero, 3)

    def test_no_se_anula_dos_veces_una_factura(self):
        operacion, factura = self.operar_con_factura()
        self.anular(operacion)
        with self.assertRaisesMessage(ValidationError, 'ya fue anulada'):
            emision.anular_factura(factura)
        self.assertEqual(NotaCredito.objects.count(), 1)
        self.assertEqual(
            EventoFactura.objects.filter(tipo=EventoFactura.ANULACION).count(), 1
        )

    def test_anular_la_operacion_de_nuevo_se_rechaza_sin_otra_nota(self):
        operacion, _ = self.operar_con_factura()
        self.anular(operacion)
        with self.assertRaisesMessage(ValidationError, 'ya fue anulada'):
            self.anular(operacion)
        self.assertEqual(NotaCredito.objects.count(), 1)

    def test_una_factura_que_nunca_se_emitio_se_anula_sin_nota_de_credito(self):
        operacion = self.operar()  # el envío no corre: la factura queda pendiente
        factura = Factura.objects.get(transaccion=operacion)
        self.assertEqual(factura.estado, Factura.PENDIENTE)

        self.anular(operacion, ejecutar_envio=False)

        factura.refresh_from_db()
        self.assertEqual(factura.estado, Factura.ANULADA)
        self.assertEqual(NotaCredito.objects.count(), 0)
        self.assertIn('Sin nota de crédito', EventoFactura.objects.get(tipo='ANULACION').detalle)
        self.assertIsNone(emision.enviar(factura.pk))  # una anulada ya no se envía

    def test_una_factura_que_espera_a_sifen_bloquea_la_anulacion_de_la_operacion(self):
        operacion, factura = self.operar_con_factura()
        Factura.objects.filter(pk=factura.pk).update(estado=Factura.ENVIADA)
        stock = self.stock()

        with self.assertRaisesMessage(ValidationError, 'espera la aprobación de SIFEN'):
            self.anular(operacion)

        operacion.refresh_from_db()
        factura.refresh_from_db()
        self.assertEqual((operacion.estado, factura.estado), ('EXITOSA', Factura.ENVIADA))
        self.assertEqual(self.stock(), stock)  # se revirtió todo, también los billetes
        self.assertEqual(NotaCredito.objects.count(), 0)

    def test_una_operacion_sin_factura_se_anula_igual(self):
        with mock.patch('apps.facturacion.emision.registrar_factura', side_effect=RuntimeError('x')), \
                self.assertLogs('apps.transacciones.models', level='ERROR'):
            operacion = self.operar()
        self.assertEqual(Factura.objects.count(), 0)
        self.anular(operacion)
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'ANULADA')
        self.assertEqual(NotaCredito.objects.count(), 0)

    def test_anular_la_operacion_sigue_devolviendo_el_stock(self):
        antes = self.stock()
        operacion, _ = self.operar_con_factura()
        self.anular(operacion)
        self.assertEqual(self.stock(), antes)

    def test_la_nota_de_credito_no_manda_otro_correo(self):
        operacion, _ = self.operar_con_factura()
        self.assertEqual(len(mail.outbox), 1)  # el de la factura
        self.anular(operacion)
        self.assertEqual(len(mail.outbox), 1)


class NotaDeCreditoYProveedorTests(BaseNotaCreditoTests):
    def test_si_el_proveedor_esta_caido_la_nota_queda_pendiente_y_se_reintenta(self):
        operacion, _ = self.operar_con_factura()
        with override_settings(FACTURACION_SIMULADOR_DISPONIBLE=False), \
                self.assertLogs('apps.facturacion.emision', level='WARNING'):
            self.anular(operacion)

        nota = NotaCredito.objects.get()
        self.assertEqual(Transaccion.objects.get(pk=operacion.pk).estado, 'ANULADA')  # no se revierte
        self.assertEqual((nota.estado, nota.intentos), (NotaCredito.PENDIENTE, 1))
        self.assertIn('no está disponible', nota.ultimo_error)
        self.assertGreater(nota.proximo_intento, timezone.now())

        resumen = emision.procesar_pendientes(ahora=nota.proximo_intento + timedelta(seconds=1))

        nota.refresh_from_db()
        self.assertEqual(resumen['enviadas'], 1)
        self.assertEqual((nota.estado, nota.ultimo_error), (NotaCredito.EMITIDA, ''))
        self.assertRegex(nota.cdc, r'^\d{44}$')

    def test_emitir_la_nota_queda_en_la_auditoria(self):
        operacion, factura = self.operar_con_factura()
        self.anular(operacion)
        evento = EventoFactura.objects.get(tipo=EventoFactura.NOTA_CREDITO)
        self.assertEqual(evento.factura, factura)
        self.assertIn('001-001-0000001', evento.detalle)

    def test_construir_la_nota_de_una_factura_sin_documento_guardado(self):
        """Las facturas de demostración no tienen ``payload``: se reconstruye desde la
        operación."""
        operacion, factura = self.operar_con_factura()
        Factura.objects.filter(pk=factura.pk).update(payload={})
        factura.refresh_from_db()
        documento = emision.construir_nota_credito(factura, 7, timezone.now())
        self.assertEqual((documento['iTiDE'], documento['dNumDoc']), ('5', '0000007'))
        self.assertEqual(documento['gCamItem'][0]['dPUniProSer'], str(int(operacion.monto_total)))


class AuditoriaDeFacturasTests(BaseNotaCreditoTests):
    def test_queda_registrada_la_emision_la_anulacion_y_la_nota_con_quien_y_cuando(self):
        operacion, factura = self.operar_con_factura()
        self.anular(operacion)

        eventos = list(factura.eventos.all())
        self.assertEqual(
            [e.tipo for e in eventos],
            [EventoFactura.EMISION, EventoFactura.ANULACION, EventoFactura.NOTA_CREDITO],
        )
        emision_, anulacion, nota = eventos
        self.assertEqual(emision_.usuario, 'sistema')  # la emite el sistema
        self.assertEqual(anulacion.usuario, self.cajero.username)  # la anula el cajero
        self.assertEqual(nota.usuario, 'sistema')
        for evento in eventos:
            self.assertIsNotNone(evento.fecha_hora)
        self.assertIn('001-001-0000001', anulacion.detalle)
        self.assertLessEqual(emision_.fecha_hora, anulacion.fecha_hora)

    def test_los_eventos_no_se_pueden_modificar_ni_borrar(self):
        operacion, factura = self.operar_con_factura()
        evento = factura.eventos.get()
        mensaje = EventoFactura.MENSAJE_INALTERABLE

        evento.detalle = 'cambiado'
        with self.assertRaisesMessage(PermissionError, mensaje):
            evento.save()
        with self.assertRaisesMessage(PermissionError, mensaje):
            evento.delete()
        with self.assertRaisesMessage(PermissionError, mensaje):
            EventoFactura.objects.update(detalle='x')
        with self.assertRaisesMessage(PermissionError, mensaje):
            EventoFactura.objects.filter(pk=evento.pk).update(usuario='otro')
        with self.assertRaisesMessage(PermissionError, mensaje):
            EventoFactura.objects.all().delete()
        with self.assertRaisesMessage(PermissionError, mensaje):
            EventoFactura.objects.bulk_update([evento], ['detalle'])

        evento.refresh_from_db()
        self.assertEqual((evento.detalle, evento.usuario), ('Emitida (CDC %s)' % factura.cdc, 'sistema'))

    def test_el_evento_sobrevive_aunque_se_intente_borrar_la_factura(self):
        _, factura = self.operar_con_factura()
        with self.assertRaises(ProtectedError):
            factura.delete()
        self.assertTrue(EventoFactura.objects.filter(factura=factura).exists())

    def test_el_admin_no_deja_agregar_modificar_ni_borrar_eventos(self):
        modelo_admin = admin.site._registry[EventoFactura]
        peticion = RequestFactory().get('/admin/')
        peticion.user = User.objects.create_superuser('super_aud', 'a@e.com', 'x')
        self.assertFalse(modelo_admin.has_add_permission(peticion))
        self.assertFalse(modelo_admin.has_change_permission(peticion))
        self.assertFalse(modelo_admin.has_delete_permission(peticion))

    def test_las_facturas_de_demostracion_dejan_constancia_de_su_emision(self):
        operacion = self.operar()
        otra = Transaccion.objects.create(
            usuario=operacion.usuario, cliente=operacion.cliente, moneda=operacion.moneda,
            metodo_pago=operacion.metodo_pago, tipo='COMPRA', cantidad=Decimal('1'),
            tasa_cambio=Decimal('7400'), estado='EXITOSA',
        )
        factura = Factura(transaccion=otra)
        factura.generar()
        evento = factura.eventos.get()
        self.assertEqual(evento.tipo, EventoFactura.EMISION)
        self.assertIn('demostración', evento.detalle)


class PantallasDeLaNotaDeCreditoTests(BaseNotaCreditoTests):
    """La factura anulada se sigue viendo, con su nota de crédito, y se puede descargar."""

    def setUp(self):
        super().setUp()
        self.final = _login_con_rol('final_nc', 'usuario_final')
        _usuario_negocio('final_nc').clientes.add(self.cliente)
        self.client.force_login(self.final)
        self.operacion, self.factura = self.operar_con_factura()
        self.anular(self.operacion)
        self.nota = NotaCredito.objects.get()

    def _texto_del_pdf(self, generador, documento):
        anterior = rl_config.pageCompression, rl_config.useA85
        rl_config.pageCompression, rl_config.useA85 = 0, 0
        try:
            return generador(documento)
        finally:
            rl_config.pageCompression, rl_config.useA85 = anterior

    def test_el_cliente_ve_su_factura_anulada_con_la_nota_de_credito(self):
        detalle = self.client.get(reverse('detalle_factura', args=[self.factura.pk]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'ANULADA')
        self.assertContains(detalle, 'Nota de crédito')
        self.assertContains(detalle, self.nota.numero)
        self.assertContains(detalle, reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        listado = self.client.get(reverse('lista_facturas'))
        self.assertContains(listado, self.factura.numero)
        self.assertContains(listado, 'ANULADA')

    def test_el_cliente_descarga_la_factura_anulada_con_su_aviso(self):
        respuesta = self.client.get(reverse('descargar_factura_pdf', args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.factura.refresh_from_db()  # la de setUp es de antes de anularla
        pdf = self._texto_del_pdf(generar_pdf, self.factura)
        self.assertIn(b'FACTURA ANULADA', pdf)
        self.assertIn(self.nota.numero.encode(), pdf)

    def test_el_cliente_descarga_el_pdf_de_la_nota_de_credito(self):
        respuesta = self.client.get(reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertEqual(
            respuesta['Content-Disposition'],
            f'attachment; filename="nota-credito-{self.nota.numero}.pdf"',
        )
        self.assertTrue(respuesta.content.startswith(b'%PDF'))
        pdf = self._texto_del_pdf(generar_pdf_nota_credito, self.nota)
        for dato in (self.nota.numero, self.factura.numero, self.nota.cdc, '80000000-0', 'PRUEBA'):
            self.assertIn(dato.encode('latin-1'), pdf, dato)

    def test_no_se_descarga_la_nota_de_la_factura_de_otro_cliente(self):
        otro = Client()
        otro.force_login(_login_con_rol('otro_nc', 'usuario_final'))
        _usuario_negocio('otro_nc')  # sin ese cliente
        respuesta = otro.get(reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 403)

    def test_una_factura_sin_nota_de_credito_no_tiene_pdf_de_nota(self):
        _, otra = self.operar_con_factura(cantidad=Decimal('5'))
        respuesta = self.client.get(reverse('descargar_nota_credito_pdf', args=[otra.pk]))
        self.assertContains(respuesta, 'no tiene una nota de crédito emitida', status_code=403)

    def test_una_nota_pendiente_todavia_no_se_puede_descargar(self):
        NotaCredito.objects.filter(pk=self.nota.pk).update(estado=NotaCredito.PENDIENTE)
        respuesta = self.client.get(reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        self.assertContains(respuesta, 'no tiene una nota de crédito emitida', status_code=403)

    def test_el_analista_consulta_y_descarga_la_nota(self):
        analista = Client()
        analista.force_login(_login_con_rol('analista_nc', 'analista'))
        self.assertEqual(analista.get(reverse('detalle_factura', args=[self.factura.pk])).status_code, 200)
        respuesta = analista.get(reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')

    def test_las_descargas_quedan_en_la_auditoria_con_el_usuario(self):
        self.client.get(reverse('descargar_factura_pdf', args=[self.factura.pk]))
        self.client.get(reverse('descargar_nota_credito_pdf', args=[self.factura.pk]))
        descargas = list(self.factura.eventos.filter(tipo=EventoFactura.DESCARGA))
        self.assertEqual(len(descargas), 2)
        self.assertTrue(all(d.usuario == 'final_nc' for d in descargas))
        self.assertIn(self.factura.numero, descargas[0].detalle)
        self.assertIn(self.nota.numero, descargas[1].detalle)

    def test_una_descarga_denegada_no_deja_evento(self):
        otro = Client()
        otro.force_login(_login_con_rol('otro_nc2', 'usuario_final'))
        _usuario_negocio('otro_nc2')
        otro.get(reverse('descargar_factura_pdf', args=[self.factura.pk]))
        self.assertFalse(self.factura.eventos.filter(tipo=EventoFactura.DESCARGA).exists())

    def test_una_factura_pendiente_sigue_sin_poder_consultarse(self):
        _, otra = self.operar_con_factura(cantidad=Decimal('5'))
        Factura.objects.filter(pk=otra.pk).update(estado=Factura.PENDIENTE)
        respuesta = self.client.get(reverse('detalle_factura', args=[otra.pk]))
        self.assertContains(respuesta, 'no fue emitida', status_code=403)
