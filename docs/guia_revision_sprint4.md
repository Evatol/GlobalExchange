# Guía de Revisión — Hito 6 / Sprint 4

Tener esta guía abierta en una pantalla aparte durante la revisión. La
profesora dirige: saltá directo a la sección que pida.

**Qué se evalúa en este hito** (ver la guía de la cátedra): SCC, PUD, ALC
(**confirmación de pago**, **notificaciones por cambios de tasa** y **módulo de
caja**), PLA, QA y CHIA. Además, se entrega la planificación del Sprint 5.

**Cómo se presenta este sprint.** Todo el trabajo se integra en `develop` y de
ahí pasa a `main` con el tag del sprint (`v1.5.0`). Lo ideal es presentar parados
en el tag: no hay diferencia entre el tag y `develop`.

Los números de esta guía son los que salen con los datos de demostración
(`seed_datos_demo`):

- USD a 7.300 (compra) / 7.400 (venta) y EUR a 7.900 / 8.050.
- `cliente_demo` opera sobre **Comercial Uno** (categoría Mayorista: comisión
  0,5%, límite de 1.000.000 Gs por operación) y tiene cuatro medios de pago:
  Caja chica, Cuenta Itaú, Tigo Money y Visa Itaú.
- `cajero_demo` atiende en **Casa Central**, con la **Caja #1 abierta** y 10
  billetes de cada denominación: PYG 1.870.000, USD 1.860, EUR 8.850 y BRL 3.870.
- Límites de stock de billetes (RF107): USD 1.850 – 3.000, EUR 500 – 20.000 y
  PYG 500.000 – 5.000.000. El mínimo de USD está justo debajo del stock inicial.

---

## 0. Antes de que llegue la profe (10 minutos antes)

1. Docker andando: `docker info`.
2. Liberar los puertos, por si quedó algo corriendo:
   `docker stop keycloak-dev` y `pkill -f 'manage.py runserver'`.
3. Estar en `develop` actualizado:

   ```
   git checkout develop
   git pull origin develop
   ```

4. Hacer **una vez** los pasos 1 y 2 de abajo. La primera vez Keycloak tarda
   en arrancar; después, frente a la profe, tarda segundos.
5. Preparar **tres sesiones a la vez**: una ventana **normal** (cliente), una
   ventana **privada** (analista) y un **segundo navegador** (cajero o
   administrador). Las ventanas privadas de un mismo navegador comparten la
   sesión entre sí, así que no sirven dos privadas para dos usuarios.

---

## 1. SCC — "Pónganse en el tag"

```
cd ~/Escritorio/IS2/GlobalExchange
./scripts/verificar_tag.sh v1.5.0
```

El script hace checkout del tag, confirma que HEAD es exactamente `v1.5.0`,
muestra su commit y termina con `OK: tag 'v1.5.0' verificado.` El aviso
amarillo de *detached HEAD* no es un error: es justo lo que se pide
demostrar. Para quedarse parado en el tag, agregar `--quedarse`.

Los tags del proyecto: `v1.0.0`, `v1.1.0`, `v1.2.0` (Sprint 1), `v1.3.0`
(Sprint 2), `v1.4.0` (Sprint 3) y `v1.5.0` (Sprint 4).

Si piden ver qué cambió en el sprint: `git log --oneline v1.4.0..v1.5.0`.

## 2. Levantar el sistema

```
./scripts/levantar_sistema.sh --limpio
```

`--limpio` borra los datos y arranca de cero: la primera operación es la #1 y
los números de esta guía coinciden exactos. Termina con **SISTEMA LISTO**.

Todos los usuarios usan la contraseña `Demo1234!`.

| Usuario | Rol | Ve |
|---|---|---|
| `admin_demo` | administrador | todo, incluidos Roles, Métodos de Pago, Banco y Cajas |
| `analista_demo` | analista | CRUD de Clientes, Monedas, Cotizaciones y Banco (solo consulta) |
| `cliente_demo` | usuario final | Divisas, Mis Medios de Pago, Operar Divisas, Historial, Mi Perfil |
| `cajero_demo` | **cajero** | solo el módulo de caja (Mi Caja y Atender cliente) |
| `angel` | sin rol | el menú básico; sirve para la demo de asignación de roles |

## 3. PUD — Pruebas y documentación

```
./scripts/pruebas.sh
```

Termina con **`Ran 505 tests ... OK`**. Los tests nuevos del sprint están en
`apps/caja/test_*.py`, `apps/pasarela/tests.py` y `apps/notificaciones/tests.py`.

```
./scripts/documentacion.sh
xdg-open docs/_build/html/index.html
```

Compila con `-W`: cualquier warning la hace fallar, igual que el CI. No queda
ningún módulo de las apps sin entrada. El registro, por fecha y por artefacto,
está en `docs/registro_pruebas_documentacion.md` (sección Sprint 4).

---

## 4. ALC — Alcance del sprint

Entrá por la pantalla pública: `http://localhost:8000/` → **Ingresar al
Portal**.

### 4.1 Confirmación de pago (E4-157 / E4-158)

Con una pasarela de pago **simulada**, pero con el protocolo de una real. Todo
por pantallas:

1. **Ventana normal** (`cliente_demo`): Operar Divisas → Comprar, USD, **13**,
   Caja chica → **Continuar al pago**.
2. En el resumen, **Pagar con la pasarela**: se abre la pantalla de la
   **pasarela de pago (simulada)** con el concepto (*Compra de 13,00 USD*), una
   **referencia** `PAS-...` y el total: **96.681 Gs**.
3. **Pagar** → vuelve al resumen: *"Pago confirmado. La operación #1 se realizó
   con éxito."* y la operación queda **Exitosa**.
4. **Rechazar** (con otra compra): *"La pasarela rechazó el pago. La operación
   #2 quedó fallida."* En el Historial, filtrá por **Fallida**.
5. **Volver sin pagar**: el resumen queda *"Esperando el pago externo"*, con el
   botón **Ir a la pasarela para pagar** para retomarlo.
6. **Cotización que cambia** (con las dos ventanas, como en el Sprint 3):
   iniciá el pago y, antes de pagar, el analista **edita** la cotización de USD
   (**7350 / 7450**) → al **Pagar**, la operación se cancela y queda anotado que
   el pago debe devolverse. **Volvé USD a 7300 / 7400 al terminar.**

🗣️ *"La pasarela simula a una empresa de pagos real: el sistema no confirma por
lo que vuelve el navegador sino por el aviso de la pasarela (el webhook), que va
firmado con HMAC-SHA256 y lo verifica el mismo código que verifica los avisos
que llegan por HTTP. Repetir el aviso no cobra dos veces, y si cambió la
cotización entre que se inició el pago y el aviso, se cancela y queda anotado
que hay que devolver el pago. Solo se paga así una compra, y no se debita
además el banco."*

**Si preguntan por SIPAP, Stripe o Bancard:** la cátedra confirmó que esta
integración se puede entregar con una **pasarela simulada**, y así quedó. No
pudimos confirmar acceso a un ambiente de pruebas de ninguno de esos servicios
desde Paraguay. La pasarela es un módulo aparte (`apps/pasarela`): para usar un
proveedor real se reemplaza esa pantalla por la página de pago del proveedor y se
agrega la verificación de su firma; el resto del flujo (referencia, webhook,
confirmación, devolución) no cambia.

**Seguridad:** la pantalla solo existe si `PASARELA_SIMULADA_ACTIVA` está
encendida, cada cliente solo llega a sus propias operaciones, y el webhook
rechaza todo aviso sin firma válida.

### 4.2 Notificaciones por cambios de tasa (E4-24 / E4-32 / E4-33)

1. **Ventana normal** (`cliente_demo`): **Mi Perfil** → en *Monedas favoritas*
   marcá **USD** → **Guardar Monedas Favoritas**.
2. **Ventana privada** (`analista_demo`): **CRUD Cotizaciones** → fila **USD** →
   **Editar** → **7500 / 7600** → guardar. (También avisa si se crea una
   cotización nueva.)
3. **Ventana normal:** en menos de 5 segundos aparece el aviso amarillo
   *"Variación Relevante: USD"*: *"Tasa Compra subió: de 7300.000000 a
   7500.000000 (2.74%) | Tasa Venta subió: de 7400.000000 a 7600.000000
   (2.70%)"*. Lo mismo pasa si el cliente está
   en **Operar Divisas**.
4. **Cerrá el aviso (×)** y recargá la página: **no vuelve**. Se marcó como
   leído.
5. **Variación chica:** editá USD a **7510 / 7610** (menos de 1%) → no avisa.
6. **Correo:** además del aviso, se manda un correo al usuario. En desarrollo
   sale por consola (el asunto va codificado, por eso se busca por otra palabra):
   `docker compose logs web | grep -B2 -A8 "Subject:"`. Con
   `./scripts/levantar_sistema.sh --con-correo` sale por Gmail de verdad.
7. **Volvé USD a 7300 / 7400** (también avisa, porque bajó más de 1%).

🗣️ *"El aviso solo le llega a quien marcó la moneda como favorita, y solo si
la variación supera el umbral (1%, configurable con
`PRICE_CHANGE_THRESHOLD_PERCENT`). Cerrar el aviso lo marca como leído. Si el
correo falla, la cotización se guarda igual y el problema queda en el log."*

### 4.3 Módulo de caja (E4-98 / E4-99 / E4-100 / E4-101)

**Administrador** (`admin_demo`): en el menú, **Sucursales y Cajeros** (Casa
Central con `cajero_demo` asignado; una sucursal admite hasta 2 cajeros),
**Denominaciones de Billetes** (26, por moneda), **Cajas** (la Caja #1,
abierta, con su botón **Balance**) y **Límites de Stock** (mínimo y máximo de
billetes por moneda).

**Cajero** (`cajero_demo`, otra sesión): el menú tiene solo **Atender cliente** y
**Mi Caja**. Si escribe otra URL (por ejemplo Operar Divisas), responde **403**.

1. **Mi Caja** → *Balance de hoy*: BRL 3.870, EUR 8.850, PYG 1.870.000, USD
   1.860 (todo es "carga inicial"), y el inventario por denominación.
2. **Atender cliente** → documento `80012345-6` (Comercial Uno), *El cliente
   compra divisas*, USD, **13** → **Calcular**:

   ```
   Compra 13,00 USD y paga 96.681,00 Gs · comisión 0,50%
   La caja recibe:  1 × 50.000 + 2 × 20.000 + 1 × 5.000 + 1 × 2.000 (PYG)
   La caja entrega: 1 × 10 + 3 × 1 (USD)
   ```

   **Confirmar operación** → *"Operación #3 confirmada. Los billetes recibidos y
   entregados se registraron automáticamente."* En **Mi Caja** aparecen los
   movimientos (entradas y salidas, con la operación) y el balance se movió.
   **Además:** el stock de USD bajó a 1.847, por debajo del mínimo (1.850), así
   que aparece el cartel rojo *"Stock bajo de USD: hay 1.847 USD en billetes y el
   mínimo configurado es 1.850."* y, arriba, un aviso amarillo *"Stock de billetes
   bajo: USD"*. El aviso le llega al cajero y a los administradores (el
   administrador lo ve en su menú).
3. **Cambio entre divisas:** *Cambio de una divisa por otra*, USD → EUR, **100**:
   *"Entrega 100,00 USD y recibe 90,22 EUR"*; la caja recibe 1 × 100 USD y entrega
   1 × 50 + 2 × 20 EUR. **Confirmar.** El stock de USD vuelve a 1.947: **la
   alerta desaparece** (y no se manda ningún aviso nuevo).
4. **Balance** (Mi Caja): USD 1.860 + 100 − 13 = **1.947**; EUR 8.850 − 90 =
   **8.760**; PYG 1.870.000 + 97.000 = **1.967.000**. Siempre cierra: *al abrir +
   carga inicial + recibido − entregado = saldo actual*.
5. **Arqueo:** en Mi Caja, en el cuadro de USD, contá **10** billetes de 100 (el
   sistema espera 11) y los demás como en el sistema (7, 10, 9, 10, 10) →
   **Registrar arqueo de USD**: *"Diferencia (contado − esperado): −100.00."* El
   arqueo no ajusta el stock.
6. **Cerrar caja** → contá USD igual que antes (las otras monedas quedan "sin
   contar") → **Cerrar caja**: *"Caja #1 cerrada. Con diferencia en: USD."* Mi
   Caja muestra **Tu último cierre** con el balance y la diferencia (−100).
7. **Administrador:** Cajas → **Balance** de la Caja #1: balance de la última
   sesión, últimos movimientos e **historial de cierres**. Para volver a
   abrirla: **Abrir** con una carga inicial (por ejemplo 2 billetes de 5 USD) →
   *al abrir* USD **1.947** (el stock se conserva) y *carga inicial* **10**.

8. **Límites de stock (RF107):** como administrador, **Límites de Stock** →
   se ven los límites cargados. Probá un valor inválido (USD mínimo **600** y
   máximo **500**) → *"USD: El mínimo no puede ser mayor que el máximo"* y **no se
   guarda ninguna fila**. Después poné USD mínimo **5000** → **Guardar límites**:
   al recargar Mi Caja del cajero aparece el cartel rojo de USD, pero **no llega un
   aviso nuevo**: el aviso salta cuando una operación **cruza** el límite, no al
   cambiar la configuración. **Volvé USD a mínimo 1850.**

🗣️ *"Los billetes los arma el sistema: va de la denominación más grande a la más
chica, usando el stock de la caja al entregar, y registra solo los movimientos y
el stock; si el cajero indica otros billetes por la API, se respetan. Todo o
nada: si no hay stock o se pasa el límite del cliente, no queda nada guardado. El
balance sale de los mismos movimientos, no de un saldo aparte, así que no se
puede desalinear. Al cerrar, el stock queda como remanente de la próxima
apertura. Y el administrador configura un mínimo y un máximo de billetes por
moneda: cuando una caja los alcanza avisa al cajero y a los administradores, una
sola vez por cruce, y la alerta queda visible en Mi Caja mientras el stock siga
fuera de límites (RF107)."*

---

## 5. CHIA

En `docs/`: los de Romina por historia (`chia_e4_24_romina.md`,
`chia_e4_32_romina.md`, `chia_e4_33_romina.md`) y los de Eva, Eduardo y Angel
del Sprint 4.

## 6. PLA

Jira: Sprint 4 con sus historias completadas y asignadas (E4-24, E4-32,
E4-33, E4-98, E4-99, E4-100, E4-101, E4-157 y E4-158), y el **Sprint 5
planificado**: integración de facturación electrónica con visualización y
descarga de facturas, terminal de autoservicio, simulación completa de
transacciones en efectivo y script de despliegue automático.

## 7. QA

- CI en cada PR: pruebas unitarias (PUN) y documentación con `-W` (PDO).
- 505 tests.
- Errores detectados y corregidos durante el sprint:
  - El pago externo (E4-157/158) tenía dos métodos de modelo sin endpoint, ni
    pantalla ni tests, y un aviso podía reabrir una operación ya fallida.
  - Los avisos de cotización nunca se marcaban como leídos y volvían a aparecer
    cada vez; **editar** una cotización no avisaba a nadie (solo crear una nueva).
  - El script de avisos armaba el texto con `innerHTML` (el nombre de la moneda
    se habría interpretado como HTML).
  - La operación presencial de caja no tenía tests.
  - Faltaba la alerta de stock mínimo/máximo de billetes que pide el ERS (RF107),
    y el cajero no podía recibir avisos en pantalla (el middleware se lo impedía).
  - Migraciones de usuarios en conflicto entre ramas (resuelto con una migración
    de fusión), y docstrings borrados al integrar (35 restaurados).

## 8. SCR — Script de despliegue automático (dejarlo para el final)

Un solo script levanta todo —código fuente, base de datos y población de datos—
en cualquiera de los dos ambientes. Va al final porque producción reemplaza a
desarrollo.

1. **Desarrollo:**

   ```
   ./scripts/levantar_sistema.sh --limpio
   ```

   Termina con **SISTEMA LISTO** y la lista de usuarios (incluido `cajero_demo`).
   Hace: verifica Docker y los puertos; con `--limpio` borra los datos previos;
   construye la imagen con el código y levanta Django, PostgreSQL y Keycloak;
   aplica las migraciones; deja el realm de Keycloak configurado (roles —incluido
   `cajero`— y usuarios demo); y carga los datos de demostración (monedas,
   cotizaciones, métodos y medios de pago, clientes, cuentas del banco, y la
   sucursal con su cajero y la caja abierta con billetes).
2. Con desarrollo levantado, abrí `http://localhost:8000/no-existe/`: la página
   amarilla de Django, con todo el detalle interno.
3. **Producción:**

   ```
   ./scripts/levantar_sistema.sh --prod --limpio
   ```

4. Recargá la misma URL: ahora solo dice **"Not Found"**.
5. Verificación completa:

   ```
   ./scripts/verificar_produccion.sh
   ```

   Tiene que terminar con **"AMBIENTE DE PRODUCCIÓN OK: 11 verificaciones
   pasaron"**.
6. Los datos también están en producción: entrá como `cajero_demo` → **Mi Caja**
   con la Caja #1 abierta; y como `cliente_demo` la pasarela de pago funciona
   igual (4.1).

🗣️ *"Mismo código, dos ambientes: gunicorn, DEBUG apagado, estáticos con
WhiteNoise y una base de datos propia. La población de datos es idempotente: no
duplica nada si se corre de nuevo, y no recarga ni reabre una caja que ya se
usó."*

Notas para si preguntan:

- Los tres avisos de `check --deploy` son por no tener HTTPS (no hay dominio ni
  certificado); está documentado en `docs/produccion.md`.
- El compose de producción de este proyecto enciende la **pasarela simulada**
  (`PASARELA_SIMULADA_ACTIVA`) y trae un secreto de demo para el webhook
  (`WEBHOOK_PAGO_SECRET`), porque este "producción" no cobra de verdad. Con un
  proveedor real la pasarela simulada debe apagarse y el secreto pasarse por
  variable de entorno.

Para volver a desarrollo:

```
docker compose -f docker-compose.prod.yml down
./scripts/levantar_sistema.sh
```

---

## 9. Preguntas que ya tenés respondidas

**"¿Por qué la pasarela es simulada?"** Porque la cátedra confirmó que se podía
entregar así, y porque no pudimos confirmar acceso a un ambiente de pruebas de
SIPAP, Bancard o Stripe desde Paraguay. Tiene el protocolo de una real (referencia,
webhook firmado, confirmación asíncrona, no doble cobro) y es un módulo aparte, para
enchufar un proveedor cambiando solo la pantalla y la verificación de firma.

**"¿Qué significa 'registro automático de movimientos' (E4-101)?"** Que el
sistema calcula solo qué billetes recibe y entrega la caja en cada operación y
registra los movimientos y el stock; el cajero no los carga a mano.

**"¿Por qué el stock no se vacía al cerrar la caja?"** Porque es el remanente
físico: es con lo que se abre la siguiente sesión. El cierre guarda una foto del
balance y, si se cuenta, la diferencia.

**"¿Una diferencia en el arqueo impide cerrar?"** No: se registra. Lo que importa
es que quede la diferencia, no bloquear la caja.

**"¿Por qué el cambio entre divisas es solo en efectivo?"** Porque las cuentas
del banco son en guaraníes.

**"¿Por qué el cajero no ve el resto del sistema?"** Porque un cajero solo
atiende en mostrador: solo accede al módulo de caja (403 en todo lo demás).

**"¿Por qué una operación presencial no deja una cancelada o fallida?"** Porque
es todo o nada: si falla algo (stock, billetes que no cierran, límite del
cliente, cotización), no se guarda nada, a diferencia del flujo digital.

**"¿Cómo se evita cobrar dos veces?"** Si cobró la pasarela, no se debita
además el banco; y repetir el aviso del webhook responde "ya procesado".

---

## 10. Si algo falla en vivo

| Problema | Solución |
|---|---|
| "Puertos ocupados" | `docker compose down` y de nuevo `./scripts/levantar_sistema.sh` |
| El login no pide credenciales | estás en una ventana con una sesión vieja: usá la privada |
| Los números no coinciden | USD quedó distinto de 7300 / 7400: corregilo en CRUD Cotizaciones; o `--limpio` |
| El aviso de cotización no aparece | el cliente no marcó USD como favorita, o la variación no superó el 1% |
| Atender cliente dice "No hay billetes suficientes" | la caja gastó billetes de esa denominación: que el administrador la reabra con otra carga |
| "No tenés una caja abierta" | la caja quedó cerrada: Cajas → **Abrir** (como administrador) |
| La pasarela da 404 | `PASARELA_SIMULADA_ACTIVA` está apagada en ese ambiente |
| Se cayó Docker | `docker compose down` y `./scripts/levantar_sistema.sh` (los datos están en volúmenes) |

## 11. Ensayo recomendado (una vez antes de la revisión)

1. `./scripts/verificar_tag.sh v1.5.0`
2. `./scripts/levantar_sistema.sh --limpio`
3. Pago por la pasarela: pagar, rechazar y cotización que cambia (4.1)
4. Favorita, edición de cotización, aviso, cerrarlo y variación chica (4.2)
5. Caja: compra (con su alerta de stock), cambio, balance, arqueo, cierre,
   reapertura y límites de stock (4.3)
6. `./scripts/pruebas.sh` y `./scripts/documentacion.sh`
7. Producción y `./scripts/verificar_produccion.sh` (8)

Si los siete pasos te salen sin leer la guía, estás listo. Con `--limpio` se
vuelve a los números de esta guía.
