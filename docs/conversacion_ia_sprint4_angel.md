# Registro de Conversación con IA (CHIA) - Sprint 4

**Integrante:** Angel Lovera (Integrante 2)
**Rol / Epic:** Módulo de Caja (E4-100 balance y cierre, E4-101 registro automático de movimientos de billetes), confirmación de pago (E4-157/E4-158, completado en la integración), notificaciones (arreglos sobre E4-24/32/33), integración del sprint y mejoras posteriores a la revisión del Sprint 3 (banco simulado, medios de pago con saldo, cambio entre divisas, categorías de cliente)
**Herramienta:** Claude Code (extensión de VS Code)
**Ramas:** `feature/banco-medios-pago-categorias`, `feature/calculadora-cambio-y-guia-sprint3`, `integracion/sprint4`, `fix/notificaciones-leidas-y-docs`, `feature/pasarela-simulada`, `docs/registro-y-guia-sprint4`, `docs/chia-sprint4`
**Fecha:** Octubre 2026

---

## 1. Resumen de Interacciones

Este sprint la IA se usó en cuatro frentes. Primero, **resolver las observaciones
de la profesora** tras la revisión del Sprint 3 (cambio entre monedas y medios de
pago con saldo), lo que terminó en un banco simulado, categorías de cliente con
límite por operación y el cambio entre divisas. Segundo, **verificar el trabajo del
equipo** (Eva, Romina y Eduardo) antes de darlo por terminado, **integrarlo** en
una sola rama y completar lo que estaba a medio hacer (el webhook de pago). Tercero,
mis propias historias del **módulo de Caja** (E4-100 y E4-101). Cuarto, la
documentación del sprint: registro de pruebas, guía de revisión, despliegue de
cero en los dos ambientes y este CHIA.

La conversación siguió un patrón: primero pedirle a la IA que **analice sin
desarrollar** y confirmar que entendió bien, y recién después pedir el desarrollo.
En varios momentos corregí a la IA (ver la sección 14), y eso cambió el resultado.

## 2. Observaciones de la profesora tras el Sprint 3

> Prompt: "Después de la presentación nos dejó esto la profe… quiero que
> analices todo lo que hay que mejorar de esta entrega, no desarrolles nada aún,
> solo quiero analizar si entendiste bien."
>
> Resultado / Impacto: la IA leyó el código y confirmó mi interpretación de los
> dos comentarios ("cambiar entre monedas aún no está, solo de guaraní" y
> "asociar a otros tipos de medio de pago"). Encontró en el código que el límite
> de compra no se iba descontando (cada operación se comparaba sola contra el
> límite) y que el tipo de método de pago era texto libre, sin efecto alguno.
> Dejó preguntas abiertas en vez de decidir sola: ¿tienen saldo todos los
> medios?, ¿se permite tarjeta de crédito en una venta?, ¿en qué moneda están las
> cuentas?

## 3. Banco simulado y medios de pago con saldo

> Prompt: "Cada medio de pago debería tener un saldo/crédito disponible que va
> bajando, si no tiene más debe avisar en el momento de confirmar el pago […]
> Sugiero que hagamos una API de un banco súper básica que vaya manejando el
> saldo." Y después: "El efectivo no tiene saldo; cuando no alcanza se rechaza la
> operación y en el historial debe aparecer como Fallida; guaraní siempre."
>
> Resultado / Impacto: se creó `apps/banco` (commit `22551e4`) con cuentas,
> billeteras y tarjetas de crédito en guaraníes, y movimientos. La IA propuso que
> fuera una app dentro del proyecto y no un servicio aparte, porque el débito y el
> cambio de estado de la operación tienen que pasar juntos o no pasar (en la misma
> base eso es una transacción atómica). Solo `apps.banco.services` mueve saldos, y
> no se expone ningún endpoint para debitar, porque con uno público un cliente
> podría acreditarse plata a sí mismo. Al confirmar, se cobra la compra o se
> acredita la venta; sin saldo la operación queda `FALLIDA` con el motivo. La
> tarjeta de crédito no se puede usar para vender (se bloquea en pantalla y en el
> servidor). Se encontró y corrigió una falla de seguridad propia: la API de
> medios de pago verificaba la cuenta con el cliente que mandaba el usuario y
> recién después lo reemplazaba por el activo, así que se podía asociar la tarjeta
> de otro cliente (hay tests que lo cubren).

## 4. Categorías de cliente y cambio entre divisas

> Prompt: "Los clientes deben tener una característica extra: VIP, mayorista y
> minorista. El VIP no tiene límites, el mayorista 1.000.000 Gs y el minorista
> 100.000. Empieza a desarrollar."
>
> Resultado / Impacto: la IA vio que ya existían dos campos parecidos (`categoria`
> y `preferencia_tipo_cambio`) y, en vez de crear un tercero, preguntó cómo
> encajaba. Se reutilizó `categoria` (Corporativo pasó a Mayorista, con una
> migración de datos) para fijar el límite **por operación**, y se eliminaron los
> límites que se cargaban a mano. Se agregó el tipo de operación `CAMBIO` entre
> divisas, que pasa por el guaraní (la casa le compra la moneda que entrega y le
> vende la que recibe) y se cancela si cambia la cotización de cualquiera de las
> dos (commits `5dcd6a6` y `700f108`). Hoy el cambio entre divisas es solo en
> efectivo, porque las cuentas del banco son en guaraníes.

## 5. Pantallas: saldo oculto, resumen simple y cotización del día

> Prompt: "No tiene sentido que ahí se pueda ver el saldo que tiene mi banco,
> debería estar oculto." / "Cambia esto, no se tiene que ver que se realizan
> tantos cálculos, además la distribución no está bien, debe ser lo más sencillo
> posible." / "Agrega esto en el menú de operación para que el usuario sepa en
> esa pantalla la cotización del día."
>
> Resultado / Impacto: la IA había mostrado el disponible de cada cuenta en el
> selector de Operar y en "Mis Medios de Pago"; se sacó de las pantallas, del
> mensaje de rechazo (que además queda en el historial) y de la API, que pasó a
> ser solo para administrador y analista. El resumen de la operación se redujo a
> tres líneas (qué comprás, cuánto pagás y con qué medio) más una línea chica con la
> cotización y la comisión. La página salía **duplicada** por un error de edición de
> la propia IA (quedó pegada una copia vieja del template); se reescribió completo y
> se agregó un test que falla si vuelve a pasar. La tabla "Cambio del Día" se
> comparte entre la pantalla pública y Operar, donde se lee desde el lado del
> cliente ("Comprás a / Vendés a").

## 6. Calculadora pública, registro de pruebas y guía del Sprint 3

> Prompt: "De acuerdo a lo que nos dijo la profe para mejorar de este sprint, ¿ya
> está?"
>
> Resultado / Impacto: la IA no dio un "sí" automático: encontró que la calculadora
> de la pantalla pública seguía convirtiendo solo contra el guaraní, y que podía
> ser justo lo que la profesora vio. Se agregó la opción de cambio entre divisas a
> la calculadora y al simulador por API (commit `51f1834`), con un test que
> comprueba que da lo mismo que una operación real sin comisión. También se cargó
> el Sprint 3 en el registro de pruebas (estaba en el Sprint 2) y se actualizó la
> guía de revisión (commit `b8ec4a3`).

## 7. ¿Puedo empezar el Sprint 4 o dependo de alguien?

> Prompt: "Teniendo en cuenta lo que me toca a mí para el próximo sprint, ¿crees
> que ya puedo empezar o dependo de alguien más?"
>
> Resultado / Impacto: la IA leyó el código de `caja` y explicó dónde estaban las
> dependencias: `Caja` no tenía cajero y `Billete` era global, algo que cambiaban
> las historias de Eva. También señaló que el registro automático de movimientos
> se engancha en `Transaccion.confirmar()`, que yo había reescrito sin mergear, y
> que el efectivo y el cambio entre divisas mueven billetes de dos monedas. Con
> eso se ordenó el trabajo: mergear primero lo mío, hablar con Eva y dejar E4-101
> para el final.

## 8. Verificar el trabajo del equipo antes de darlo por terminado

> Prompt: "Me dicen mis compañeros que ellos ya terminaron sus partes, ¿puedes
> verificarlo en el git?"
>
> Resultado / Impacto: en vez de confiar en el "ya está", se mergeó cada rama sobre
> `develop` en una copia aislada (`git worktree`) y se corrieron migraciones y
> tests. Se encontró que **solo E4-157/158 de Eduardo estaba mergeado, y estaba
> incompleto**: tenía dos métodos de modelo que nadie llamaba (sin endpoint, sin
> pantalla, sin tests) y su commit había borrado 28 docstrings. Las ramas de
> Romina (E4-24/32/33) tenían una migración con el mismo número que la mía y un
> conflicto en `divisas/views.py`; las de Eva (E4-98/99) pasaban 337 tests pero no
> tenían PR. También se vio que Eva ya había hecho parte de E4-100 y E4-101
> (`abrir_caja` y `registrar_movimientos_billetes`).

## 9. Integración de las ramas del sprint

> Prompt: "Me dieron el permiso de modificarlo todo yo para que quede funcional,
> ¿por dónde empezamos?" Y después: "Haz todo el punto 1, pero sin modificar el
> nombre de clases, variables, etc. que usaba Romina, porque ella luego se pierde al
> explicarle su parte a la profe."
>
> Resultado / Impacto: se armó `integracion/sprint4` uniendo las ramas de Eva y de
> Romina con sus commits originales. Para el choque de migraciones se **evitó
> renumerar las de Romina** (su base local ya las tenía aplicadas y habría fallado) y
> se agregó una migración de fusión; en `divisas/views.py` se conservaron sus
> enganches (`procesar_cambio_cotizacion`, `cotizacion_obj`) junto al simulador con
> cambio de divisas. Se restauraron 35 docstrings que esas ramas habían borrado
> (7 en `919bb84` y 28 en `f1d39ea`; solo docstrings, la lógica no cambia). Se verificó con una prueba de punta a punta
> (favorita, cambio de cotización, aviso interno, correo y endpoint).

## 10. Completar E4-157 / E4-158: webhook y pasarela de pago

> Prompt: "Sigue con eso." (completar el webhook de Eduardo). Después: "si hacemos
> el de prueba, ¿cómo funcionaría?" y "hagamos eso pero que no sea nada por
> terminal, hazlo completo."
>
> Resultado / Impacto: se completó con un webhook sin login cuya autenticidad la da
> una firma HMAC-SHA256 del cuerpo (sin firma válida, o sin secreto configurado,
> rechaza todo), idempotente y con bloqueo de fila (se probó con dos avisos
> simultáneos reales). Se corrigieron dos fallas de su diseño: un aviso podía
> reabrir una operación ya fallida o cancelada, y no había protección contra el
> doble cobro (si cobró la pasarela, no se debita además el banco). Se conservaron
> sus nombres (`iniciar_pago_externo`, `confirmar_pago_webhook`,
> `referencia_pago_externo`, `PENDIENTE_PAGO`, `PAGADO`; commit `f1d39ea`).
> Como la guía de la cátedra pide integración con SIPAP, Stripe o similares, la IA
> investigó las opciones: no pudimos confirmar acceso a un ambiente de pruebas de
> ninguna desde Paraguay (Stripe parece no soportar cuentas paraguayas, y de Bancard
> y Pagopar no se halló documentación de pruebas accesible). Se decidió construir una
> **pasarela simulada completa por pantallas**, con el protocolo de una real:
> pantalla de pago, aviso firmado y confirmación solo por el webhook (commit
> `718d58a`), apagable con `PASARELA_SIMULADA_ACTIVA`. Se probó por HTTP real contra
> un servidor levantado. Más adelante informé en la conversación que la profesora
> confirmó que se puede entregar con la pasarela simulada, sin proveedor real, y con
> eso quedó cerrado el punto de confirmación de pago del alcance.

## 11. Módulo de Caja: E4-100 y E4-101

> Prompt: "Vamos con mis historias."
>
> Resultado / Impacto: la IA mostró primero qué faltaba de cada historia. Para
> **E4-100** (apertura, balance y cierre) la apertura ya existía; se agregó el
> balance (al abrir + carga inicial + recibido − entregado = saldo actual, calculado
> desde los movimientos, sin un saldo aparte) y el cierre, que guarda el balance de
> la sesión y permite contar billetes dejando un arqueo con su diferencia. Para
> **E4-101** el cajero cargaba los billetes a mano y no había pantalla; se hizo que
> el sistema arme solo el desglose en billetes (de la denominación más grande a la
> más chica, limitado por el stock al entregar) y se agregó la pantalla "Atender
> cliente" con vista previa. La operación presencial **no tenía tests**; se
> escribieron 54 (commit `a07d445`). También hizo falta el rol `cajero` en Keycloak y
> un `cajero_demo` con su caja abierta (commit `3156b41`).

## 12. Notificaciones: tres fallas encontradas

> Prompt: "Listo, puedes verificar si quedó bien y después seguimos." (y a
> continuación, el punto de las notificaciones y la documentación del plan).
>
> Resultado / Impacto: al revisar las notificaciones de Romina se encontró que los
> avisos **nunca se marcaban como leídos** (volvían a aparecer cada vez), que el
> script armaba el texto con `innerHTML` (el nombre de una moneda se habría
> interpretado como HTML) y que solo corría en el menú principal. Se arregló con un
> endpoint para marcar como leído al cerrar el aviso y se agregaron los avisos a la
> pantalla de Operar, conservando sus nombres (commit `f249cae`). Después, al
> escribir la guía, se descubrió otra: **editar una cotización no disparaba el
> aviso**, solo crear una nueva (commit `6f395ad`). Un test de la propia IA atrapó
> además un error suyo: un comentario `{# #}` de varias líneas se imprime como texto
> en Django.

## 13. Análisis de la API de Factura Segura y de las guías

> Prompt: "Una cosa más antes de mergear todo, la profe nos pasó esto para
> integrarlo al proyecto, ¿en qué parte hay que utilizarlo? No lo integres todavía,
> pero dime dónde usarlo y si es fácil de integrar."
>
> Resultado / Impacto: la IA leyó el PDF de la API y propuso integrarla en
> `apps/facturacion`, enganchada al final de `Transaccion._procesar_pago`, con un
> modo simulado. Detectó que faltan datos del emisor, el email del cliente y el
> timbrado, y dejó preguntas para la profesora. Luego se vio en la guía de la
> cátedra que es del **Sprint 5** (Hito 7), junto con la terminal de autoservicio y la
> simulación en efectivo, así que no se integró.

## 14. Errores de la IA y cómo se corrigieron

Esta sección existe porque pasó, y porque forma parte de usar bien la
herramienta:

- **Saldo visible al cliente:** la IA mostró el saldo del banco en el selector de
  medios de pago; lo detecté yo y lo corrigió en las cuatro pantallas y la API.
- **Resumen duplicado:** un reemplazo de bloques de texto dejó pegada una copia
  vieja del template; lo señalé con una captura. Se reescribió y se agregó un test.
- **`git checkout --ours` en un merge:** descartó también los cambios de Romina que
  se habían fusionado solos; la IA lo detectó al verificar y rehízo el merge
  resolviendo solo las dos zonas en conflicto.
- **`git stash` accidental:** un comando de diagnóstico guardó todo el trabajo sin
  commitear; se recuperó enseguida y se volvió a correr la suite sin diferencias.
- **`git add -A` incluyó un archivo ajeno** (`guia_revision_sprint2.md`): se sacó
  del commit antes de subirlo.
- **Hash equivocado en el registro de pruebas** al reemplazar un marcador: se
  detectó al verificar que cada hash citado existe y coincide con su fila.
- **Conteo de tests por commit con un desvío de 1** frente a las corridas reales:
  se investigó hasta encontrar la causa (Romina extendió tests en vez de crear
  nuevos) en lugar de ajustar el número.
- **PRs abiertos contra `main` en vez de `develop`:** el #48 se abrió así y se
  corrigió antes de mergear; el #51 sí se mergeó a `main`, y como su rama partía de
  `develop` llevó todo el sprint a `main` (sin perder nada, pero dejó a `develop`
  4 commits atrás). Son errores del flujo de trabajo, no de la IA, y se detectaron
  revisando el estado real de las ramas.
- **Dueño equivocado del módulo de caja:** la IA dijo que había que hablar con
  Eduardo por `Caja` y `Billete`; después corrigió que las historias E4-98/99 son de
  Eva (Eduardo tiene los pagos externos).

## 15. Registro de pruebas, guía del Sprint 4 y despliegue de cero

> Prompt: "Haz el punto 4."
>
> Resultado / Impacto: se cargó el Sprint 4 en el registro de pruebas (292 → 460
> tests) contando los tests de cada commit contra su padre y comparando con las
> corridas reales; se escribió la guía de revisión del Sprint 4 ejecutando toda la
> demo sobre datos de prueba para citar números y mensajes reales; y se **desplegó
> el sistema de cero** en los dos ambientes: desarrollo termina en "SISTEMA LISTO" y
> producción en "AMBIENTE DE PRODUCCIÓN OK: 11 verificaciones pasaron", con el rol
> cajero, la caja abierta, el webhook y la pasarela funcionando en ambos. Eso
> encontró que el compose de producción no pasaba el secreto del webhook (rechazaba
> todo) y que el cartel final no mencionaba al cajero demo (commit `46d9b8b`).

## 16. Contraste con el ERS: alerta de stock de billetes (RF107)

> Prompt: (adjunté la guía de la cátedra y el ERS) "¿no hay nada más que
> falte?" Y después: "Implementa eso: un límite mínimo y máximo por moneda,
> configurable por el administrador, y un aviso a administradores y cajero, y
> visible en Mi Caja."
>
> Resultado / Impacto: al contrastar el sprint con el ERS la IA encontró que
> **RF107** pide notificar cuando el stock de billetes de una moneda llega a un
> límite mínimo o máximo configurado, y que no existía (lo había buscado en el
> código). Se implementó (commit `3051ec8`): límites por moneda en la propia moneda,
> configurables desde una pantalla y la API; el aviso se manda solo cuando una
> operación **cruza** el límite, comparando el estado antes y después de cada
> movimiento, para no avisar en cada operación; y la alerta vigente se muestra en
> Mi Caja, en Atender cliente y en el balance del administrador. Al hacerlo salió
> a la luz que el cajero **no podía recibir avisos en pantalla**, porque el
> middleware de su rol solo le dejaba `/api/caja/`; se le permitió únicamente
> `/api/notificaciones/` (que solo devuelve los avisos propios). Se probó por HTTP
> real con los datos de la demo: comprar 13 USD baja el stock a 1.847 (el mínimo es
> 1.850) y dispara la alerta y un único aviso por destinatario; el cambio de 100 USD
> la normaliza. Se detectó también, y quedó anotado, que RF110 (mostrar el número de
> atención al cliente) no está implementado, aunque no es de este sprint.

## 17. Archivos / evidencia

- Código: `apps/banco/`, `apps/pasarela/`, `apps/caja/services.py` y
  `apps/caja/test_cierre_movimientos.py`, `apps/transacciones/webhook.py`,
  `apps/divisas/views.py` (aviso al editar), `apps/usuarios/templates/usuarios/_notificaciones_tiempo_real.html`.
- Documentación: `docs/registro_pruebas_documentacion.md` (Sprint 3 y 4),
  `docs/guia_revision_sprint4.md`, `docs/guia_revision_sprint3.md` (actualizada).
- PRs: #43 (banco, medios de pago, categorías), #44 (calculadora y guía), #48
  (integración del sprint), #49 (notificaciones), #50 (pasarela), #51 (registro y
  guía).
- Resultado: 220 tests al empezar el trabajo del sprint y 505 al cerrarlo, con
  Sphinx en `-W` sin warnings y el CI en verde.
