from decimal import Decimal
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from apps.notificaciones.models import Notificaciones
from apps.usuarios.models import Usuario

def procesar_cambio_cotizacion(cotizacion_nueva, cotizacion_anterior=None):
    """
    Evalúa si la variación entre la cotización anterior y la nueva supera el umbral (E4-32)
    y genera notificaciones internas y por correo (E4-33) para los usuarios que tienen la moneda como favorita.
    """
    if not cotizacion_anterior:
        return None

    umbral_percent = getattr(settings, 'PRICE_CHANGE_THRESHOLD_PERCENT', 1.0)
    
    # Tasas anteriores y nuevas
    tc_ant = Decimal(str(cotizacion_anterior.tasa_compra))
    tc_nueva = Decimal(str(cotizacion_nueva.tasa_compra))
    tv_ant = Decimal(str(cotizacion_anterior.tasa_venta))
    tv_nueva = Decimal(str(cotizacion_nueva.tasa_venta))

    # Cálculo de porcentaje de variación
    var_compra = abs((tc_nueva - tc_ant) / tc_ant * 100) if tc_ant > 0 else Decimal('0')
    var_venta = abs((tv_nueva - tv_ant) / tv_ant * 100) if tv_ant > 0 else Decimal('0')

    supera_compra = var_compra > Decimal(str(umbral_percent))
    supera_venta = var_venta > Decimal(str(umbral_percent))

    if not (supera_compra or supera_venta):
        return None

    # Determinar dirección del cambio
    dir_compra = "subió" if tc_nueva > tc_ant else "bajó"
    dir_venta = "subió" if tv_nueva > tv_ant else "bajó"

    moneda = cotizacion_nueva.moneda
    mensaje_partes = []

    if supera_compra:
        mensaje_partes.append(f"Tasa Compra {dir_compra}: de {tc_ant} a {tc_nueva} ({var_compra:.2f}%)")
    if supera_venta:
        mensaje_partes.append(f"Tasa Venta {dir_venta}: de {tv_ant} a {tv_nueva} ({var_venta:.2f}%)")

    detalle = " | ".join(mensaje_partes)
    titulo = f"Variación Relevante: {moneda.codigo}"
    mensaje = f"La cotización de {moneda.nombre} ({moneda.codigo}) ha variado significativamente. {detalle}"

    # Filtrar solo usuarios que tienen esta moneda como favorita
    usuarios_favoritos = Usuario.objects.filter(monedas_favoritas=moneda)

    notificaciones_creadas = []
    for usuario in usuarios_favoritos:
        # 1. Crear notificación interna (E4-32)
        notif = Notificaciones.objects.create(
            usuario=usuario,
            titulo=titulo,
            mensaje=mensaje,
            tipo='variacion_cotizacion',
            leida=False
        )
        notificaciones_creadas.append(notif)

        # 2. Enviar notificación por correo electrónico de forma segura tras el commit (E4-33)
        if getattr(usuario, 'email', None):
            def enviar_correo_seguro(u_email=usuario.email, subj=titulo, msg=mensaje):
                try:
                    send_mail(
                        subject=subj,
                        message=msg,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[u_email],
                        fail_silently=False,
                    )
                except Exception as e:
                    # Criterio: Si falla el envío del correo, la cotización se guarda igual
                    print(f"Advertencia: No se pudo enviar el correo a {u_email}: {e}")

            transaction.on_commit(enviar_correo_seguro)

    return notificaciones_creadas