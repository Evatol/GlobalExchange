# Facturación electrónica

Cada operación que termina **Exitosa** (digital o en efectivo, compra, venta o cambio)
genera su factura electrónica automáticamente. El cliente las consulta y las descarga en
PDF desde **Facturas** (`/api/facturacion/gestion/facturas/`, pantallas de `apps/facturacion/services.py` y `views.py`).

## Cómo funciona

1. Al pasar la operación a Exitosa se crea la factura en estado **Pendiente de envío**,
   con su número legal correlativo (`001-001-0000001`) y el documento ya armado. Eso
   ocurre en la misma transacción de base de datos que la operación: o quedan las dos o
   ninguna, y una operación no puede tener dos facturas.
2. Cuando esa transacción se confirma, la factura se envía al proveedor. **Nunca revierte
   ni toca la operación**: si el proveedor no está disponible o contesta con error, la
   operación sigue Exitosa y la factura sigue pendiente, con el motivo y la hora del
   próximo reintento (1, 2, 4, 8... minutos, hasta una hora).
3. En cuanto la factura queda **Emitida**, se le manda por **correo** al cliente, con el
   PDF adjunto. El correo va al del usuario que hizo la operación (el cliente no tiene
   correo propio) y sale una sola vez. Si el correo falla, la factura sigue emitida con el
   motivo en `correo_error` y se reintenta. Con `FACTURACION_ENVIAR_CORREO=false` no se
   manda. Con Factura Segura, además, ella le manda al receptor su propio correo con el
   XML firmado y el KuDE.
4. `manage.py procesar_facturas` (para correr cada pocos minutos) reintenta las pendientes,
   consulta a SIFEN las enviadas y reenvía los correos que no salieron. También crea la
   factura de las operaciones exitosas que no la tengan.

| Estado | Significa |
|---|---|
| Pendiente de envío | Todavía no se pudo enviar (o no llegó la hora del reintento) |
| Enviada a SIFEN | El proveedor la recibió y SIFEN todavía no resolvió |
| Emitida | SIFEN la aprobó: ya se puede ver y descargar |
| Rechazada | SIFEN la rechazó (el motivo queda en la factura) |
| Anulada | La operación en efectivo se anuló y la factura quedó anulada con su nota de crédito |

El cliente ve en su listado todas sus facturas, pero solo abre el detalle y descarga el
PDF de las **Emitidas**. El analista y el administrador consultan las de todos los
clientes, solo lectura.

## Anular una factura: la nota de crédito (E4-191)

Cuando el cajero **anula una operación en efectivo** desde *Mi caja* (E4-196), su factura se
anula también, en la misma transacción de base de datos:

| La factura estaba | Qué pasa |
|---|---|
| **Emitida** | Queda **Anulada** y se crea su **nota de crédito** por el monto total, con su propia numeración (`001-001-0000001`, independiente de la de facturas) y la referencia al CDC de la factura. La nota se envía al proveedor, se reintenta si falla y queda emitida o rechazada, igual que una factura |
| **Pendiente** o **Rechazada** | Queda Anulada **sin** nota de crédito: nunca existió para SIFEN |
| **Enviada a SIFEN** (esperando la aprobación) | **Se rechaza la anulación de la operación** con un mensaje claro y no cambia nada: se puede anular cuando la factura quede emitida |
| **Anulada** | Se rechaza: "La factura ... ya fue anulada" (no se emite otra nota) |

El cliente sigue viendo su factura anulada en **Facturas**, con el detalle de la nota de crédito
y su descarga en PDF (`/api/facturacion/gestion/facturas/<id>/nota-credito/pdf/`), con las mismas
reglas de acceso que la factura. Si el proveedor está caído al anular, la operación queda
anulada igual y la nota queda pendiente: `manage.py procesar_facturas` la reintenta.

La nota de crédito no se manda por correo (solo la factura).

## Auditoría de las facturas (E4-191, RF98)

Cada factura tiene un registro de eventos (`EventoFactura`) con **quién, qué y cuándo**:

* **Emisión**: cuando la factura queda emitida (la hace el sistema).
* **Descarga**: cada vez que alguien descarga el PDF de la factura o de su nota de crédito
  (con el usuario que lo hizo; las descargas denegadas no dejan evento).
* **Anulación**: con el usuario que anuló la operación (el cajero) y el detalle de la nota.
* **Nota de crédito emitida**: cuando el proveedor la aprueba.

El registro es **inalterable**: un evento no se puede modificar ni borrar (ni por instancia ni en
bloque: `PermissionError`), no se borra junto con la factura (`PROTECT`) y en el admin de Django
es de solo lectura. Es una garantía de la aplicación; no hay un bloqueo a nivel de base de datos.

## Proveedores

`FACTURACION_PROVEEDOR` elige a quién se le envía:

* **`simulado`** (por defecto): aprueba al instante y fabrica un CDC con la forma de uno
  real. No necesita credenciales. Sus facturas no tienen validez tributaria y el PDF lo
  dice. Con `FACTURACION_SIMULADOR_DISPONIBLE=false` responde como si estuviera caído,
  para mostrar el reintento.
* **`facturasegura`**: la API de Factura Segura (ESI), que genera el documento
  electrónico, lo firma y lo manda a SIFEN. Necesita:
  1. un usuario ESI registrado en el portal de pruebas (`https://test.facturasegura.com.py`)
     y su token (`POST https://apitest.facturasegura.com.py/login?include_auth_token`);
  2. que soporte@facturasegura.com.py autorice ese usuario para `/misife00/v1/esi` y lo
     asocie al emisor;
  3. el emisor dado de alta en Factura Segura (RUC, timbrado, certificado de firma).

  Con eso: `FACTURACION_PROVEEDOR=facturasegura`, `FACTURA_SEGURA_TOKEN=...` y los datos
  del emisor y del timbrado (ver `.env.example`).

> **Importante:** el cliente de Factura Segura está hecho contra el contrato del documento
> de la API y probado con respuestas simuladas, pero **nunca se probó contra el servicio
> real** (no hay credenciales). Los códigos de SIFEN que arma `construir_documento`
> (tipo de operación, tipo de pago, forma de procesamiento de la tarjeta, etc.) están
> tomados del Manual Técnico de SIFEN y hay que confirmarlos en la primera prueba real:
> si alguno no corresponde, Factura Segura responde con un `code` negativo y el motivo, la
> factura queda pendiente con ese motivo en `ultimo_error` y se corrige en
> `apps/facturacion/emision.py`.

## Supuestos que conviene confirmar con la cátedra

* La operación se factura **completa** (el total que paga o recibe el cliente) como un
  único ítem **exento de IVA**. Si la casa de cambio debe facturar solo la comisión, o con
  IVA, cambia `construir_documento`.
* El correo del receptor es el del usuario que operó (Factura Segura lo exige y el
  cliente no tiene correo propio).
* Los datos del emisor, el timbrado y la numeración de los valores por defecto son de
  **demostración**.

## Demo por pantalla

1. Como `cliente_demo`, comprar USD en efectivo y **Confirmar pago**: en el resumen aparece
   *Factura electrónica 001-001-000000X* con *verla* y *descargar PDF*. También en
   **Facturas** (menú). En desarrollo el correo se imprime en la terminal del servidor
   (con el PDF adjunto); con SMTP configurado (`EMAIL_BACKEND`, ver `.env.example`) llega a
   la bandeja del usuario.
2. **Ver** muestra el detalle (montos, tasa, comisión, operación). **PDF** lo descarga.
3. Filtrar por fecha, número, moneda o estado.
4. Como `analista_demo`: **Facturas** muestra las de todos los clientes, con filtro por
   cliente, y no se puede modificar nada.
5. **Reintento:** con `FACTURACION_SIMULADOR_DISPONIBLE=false` en el `.env` (y reiniciando),
   confirmar una compra: la operación queda Exitosa y la factura *Pendiente de envío*. Con
   el simulador otra vez disponible: `venv/bin/python manage.py procesar_facturas`.
6. **Anulación (E4-191):** como `cajero_demo`, atender a un cliente en el mostrador (una
   compra en efectivo) y, en **Mi caja → Últimas operaciones**, pulsar **Anular**. La
   factura de esa operación pasa a *ANULADA* y se emite su nota de crédito. Como el cliente,
   en **Facturas** se ve la factura anulada, con su nota de crédito y su PDF. En el admin de
   Django, *Eventos de factura* muestra la auditoría (emisión, anulación y nota de crédito).
