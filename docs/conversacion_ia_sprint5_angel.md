# Registro de Conversación con IA (CHIA) - Sprint 5

**Integrante:** Angel Lovera (Integrante 2)
**Rol / Epic:** pasarela de pago Stripe, facturación electrónica (emisión automática y envío por correo, E4-189), anulación de factura con nota de crédito (E4-191), integración de todo el sprint, terminal de autoservicio (E4-193 ingresar y E4-194 operar en efectivo) y corrección de la anulación en efectivo (E4-196, de Eduardo).
**Herramienta:** Claude Code (extensión de VS Code), modelo Claude Sonnet 5.5
**Ramas:** `wip/angel-stripe-facturacion`, `fix/E4-196-anulacion-efectivo`, `feature/E4-191-anular-factura`, `feature/E4-193-194-terminal-quiosco`, `integracion/sprint5`, `fix/umbral-y-chia-sprint5`
**PR:** #62 (integración del sprint, mergeado a `develop`)
**Fecha:** Octubre - Noviembre 2026

---

## 1. Resumen de Interacciones

Este sprint la IA se usó en cinco frentes. Primero, **la pasarela Stripe** que pidió la
profesora para toda operación que no sea en efectivo. Segundo, **la facturación
electrónica** contra la API de Factura Segura que nos compartió la cátedra: emisión
automática, reintentos, PDF y correo al cliente. Tercero, **verificar el trabajo de
Eva, Romina y Eduardo**, corregir lo que estaba mal e **integrar las cuatro ramas en una
sola** (`integracion/sprint5`, PR #62). Cuarto, mis historias nuevas: anular la factura
(E4-191) y la terminal de autoservicio (E4-193 y E4-194). Quinto, **contrastar el sprint
con la guía de la cátedra, el ERS y la API** para ver qué faltaba antes de entregar.

El patrón de trabajo se mantuvo del Sprint 4: pedirle a la IA que **revise y analice
antes de desarrollar**, exigir que **pruebe lo que dice** (tests, `makemigrations
--check`, Sphinx con `-W`, pruebas sobre el sistema en marcha) y **corregirla** cuando se
equivoca (sección 11).

## 2. Pasarela de pago Stripe

> Prompt: "La profe nos pidió implementar para la pasarela de pago Stripe… necesito que
> implementes la pasarela de pago para todas las operaciones, siempre y cuando estas no
> se hagan por efectivo. ¿Qué necesitás que te pase para que lo hagas?" Después, con la
> cuenta de Stripe en modo de prueba: "¿Qué país pongo si no veo Paraguay en Stripe?"
>
> Resultado / Impacto: la IA explicó de dónde sacar las claves de prueba (las puse
> solo en el `.env`, que git ignora, y no volvieron a aparecer en mensajes ni en commits)
> y dejó decididas con mi aceptación estas reglas: la **compra** con un medio que no es
> efectivo pasa por Stripe Checkout, cobrando en guaraníes (moneda sin decimales, el
> monto va en enteros); la **venta** sigue acreditándose en el banco simulado, porque
> pagarle a un cliente exigiría Stripe Connect; la pasarela **simulada se conserva**
> (`PASARELA_PROVEEDOR=stripe|simulada`) para poder mostrar el caso de saldo
> insuficiente que pidió la profesora en el Sprint 3; y si el cliente pagó y la
> operación ya no se puede realizar (cambió la cotización o la canceló justo antes) se
> le **reembolsa solo**. Stripe no ofrece cuentas en Paraguay, así que la cuenta de
> prueba quedó en Estados Unidos. Las pruebas fuerzan los proveedores simulados y
> mockean la librería `stripe`: ningún test llama a la red. Llegué hasta el checkout de
> Stripe en modo de prueba.

## 3. Planificación del Sprint 5 en Jira con Rovo

> Prompt: (pegué el plan de sprint que armó Rovo) "Dime si le cambiamos algo." Después:
> "Solo dame el prompt para Rovo", "Está haciendo cualquier cosa, dame otro prompt",
> "Ya borré todo lo que hizo, dame un prompt de acuerdo a eso", "Mejor dame las 10
> historias que quieres que se creen" y "Solo se creó esto, dame un prompt para que cree
> solo las 9 que faltan y que no le tenga que confirmar cada una".
>
> Resultado / Impacto: Rovo (el asistente de Jira) tuvo resultados inconsistentes: en
> una pasada hizo cosas que no correspondían (borré todo lo que había creado) y pedía
> confirmación en cada historia. La IA no puede escribir en Jira, así que su aporte fue
> **redactar los prompts y la lista de las 10 historias** (E4-189 a E4-198) hasta que
> quedaron cargadas las que faltaban.

## 4. Facturación electrónica y correo de la factura

> Prompt: (adjunté "API de Factura Segura para ESI", la guía de la cátedra y el ERS)
> "Funcionó bien, ahora quiero hacer la implementación…" Más tarde: "La factura no tiene
> que llegar también por el correo electrónico asociado al cliente que hace la
> operación?"
>
> Resultado / Impacto: la IA leyó la API y propuso este diseño, que se implementó
> (`apps/facturacion/emision.py`, `proveedores.py`, `docs/facturacion.md`):
> - al pasar una operación a **EXITOSA** se crea su factura en la **misma transacción**
>   de base de datos (con una restricción uno a uno, así no hay facturas duplicadas) y
>   se envía al confirmarse la transacción;
> - **un fallo de facturación nunca revierte el pago**: la factura queda pendiente y
>   `manage.py procesar_facturas` la reintenta con espera creciente (de 1 a 60
>   minutos), crea las que falten y consulta las enviadas a SIFEN;
> - dos proveedores: `simulado` (por defecto, aprueba al instante) y `facturasegura`
>   (`calcular_de` + `generar_de` + `get_estado_sifen`), elegidos con
>   `FACTURACION_PROVEEDOR`;
> - tras mi pregunta, la factura emitida se **envía por correo al usuario que hizo la
>   operación**, con el PDF adjunto, una sola vez, y un correo caído no afecta a la
>   factura.
>
> También reporté que una cuenta nueva **iniciaba sesión sin verificar el correo**; se
> activó la verificación de correo en Keycloak y el envío por SMTP quedó configurable por
> variables de entorno (`configure_keycloak_registration.py`, `.env.example`). La
> contraseña de aplicación de Gmail vive solo en el `.env`.
>
> **Límite que dejé documentado:** el cliente de Factura Segura **nunca se probó contra
> el servicio real** (falta el token y la asociación del emisor). Los códigos SIFEN del
> documento (tipo de pago, tipo de operación, factura exenta con un solo ítem por el
> total) son supuestos del manual que hay que confirmar con la cátedra.

## 5. Revisar el trabajo del equipo y corregir a Eduardo

> Prompt: "¿Puedes revisar el git y decirme cómo van mis compañeros? ¿Van por buen
> camino?" Después: "Lo que hizo Edu, ¿lo podemos corregir?"
>
> Resultado / Impacto: la IA revisó las ramas y encontró que la rama E4-193 de Romina
> era solo una mezcla de E4-192 (no tenía quiosco), que los CHIA de Eduardo en `develop`
> estaban vacíos (0 bytes) y que el PR #59 de Eduardo (E4-194/196/197) tenía tres
> problemas: **borraba docstrings**, la **anulación en efectivo era inalcanzable para el
> cajero** (estaba bajo `/api/transacciones/`, donde su rol no puede entrar) y
> **faltaba la migración** del estado `ANULADA`. Se corrigió en
> `fix/E4-196-anulacion-efectivo`: el cajero anula desde "Mi caja", se restauraron los
> docstrings, se agregó la migración `transacciones/0006_estado_anulada` y 20 tests
> (`apps/caja/test_anulacion.py`).

## 6. Integrar las cuatro ramas

> Prompt: "Hagamos todo esto" (sobre el plan de integración que propuso la IA).
>
> Resultado / Impacto: `integracion/sprint5` unió lo de Eva (E4-190, E4-195, E4-198), lo
> de Romina (E4-192), la corrección de Eduardo, y mi trabajo de Stripe y facturación. Al
> integrar aparecieron **defectos que ninguna rama tenía por separado**:
> - E4-190 (consultar facturas) y E4-198 (despliegue) traían **dos versiones casi
>   idénticas de la facturación** que chocaban; se dejó la de Eva (`Factura.numero` es su
>   propiedad, el campo pasó a llamarse `correlativo`, con una migración `RenameField`) y
>   mi motor de emisión se adaptó encima;
> - el **cierre por inactividad** de Eva (E4-195) estaba escrito pero **no registrado**
>   en `settings.py`, o sea que no funcionaba;
> - la **caja de una terminal nacía cerrada**, aunque la terminal estuviera activa, así
>   que su stock no contaba como disponible;
> - dar de baja una terminal **salteaba la sincronización** de su caja;
> - el seed de demo modelaba la terminal como una sucursal con un cajero técnico: había
>   **0 filas de `Terminal`** en la base.
>
> Resultado: 703 tests al integrar, 712 tras corregir E4-192, con `makemigrations
> --check` limpio y Sphinx con `-W` (probado sobre una base migrada). Las ramas de Eva
> y Romina no se tocaron: sus commits conservan la autoría.

## 7. Anular la factura (E4-191)

> Prompt: (adjunté la captura del chat con Romina) "Me dijo esto, ¿podemos seguir todo lo
> que se pueda sin ella?"
>
> Resultado / Impacto: al **anular una operación en efectivo** desde "Mi caja", la
> factura emitida pasa a **ANULADA** y se crea una **nota de crédito** con numeración
> propia y el mismo envío con reintentos. Una factura pendiente o rechazada se anula sin
> nota; una factura **enviada a SIFEN y todavía sin respuesta bloquea** la anulación de
> la operación. Se agregó una **auditoría inalterable** (`EventoFactura`: emisión,
> descarga, anulación y nota; no se puede modificar ni borrar, y en el admin es de solo
> lectura). 28 tests en `test_nota_credito.py`; la suite pasó a 740.

## 8. Terminal de autoservicio: E4-193 y E4-194

> Prompt: "E4-193 y E4-194: esperan el push de Romina, esto no lo puedo hacer yo?"
>
> Resultado / Impacto: la IA había recomendado **esperar el push de Romina**; al
> preguntarle si no podía hacerlo yo, respondió que sí y lo implementó, avisando del
> **riesgo de duplicar trabajo** (que se resolvió al integrar su rama, más abajo). Quedó:
> - inicio **público** de cada terminal con las cotizaciones y la calculadora (que pasó a
>   ser un parcial compartido con la pantalla pública);
> - identificación con **Keycloak**; desde ahí la sesión queda marcada como de quiosco y
>   un middleware responde **403** fuera de las pantallas del autoservicio;
> - elección del cliente cuando el usuario tiene varios, y mensajes claros si no tiene
>   ninguno o están dados de baja;
> - **operar en efectivo** (compra, venta o cambio): vista previa con tasa, comisión,
>   total, límite de la categoría y los billetes a ingresar y a entregar; al confirmar,
>   la operación queda EXITOSA **sobre la caja de la terminal** (modalidad `TERMINAL`),
>   con su factura y un comprobante con el desglose; si falla por stock, límite o cambio
>   de cotización **no se mueve ningún billete** y queda **FALLIDA**.
>
> Cuando Romina subió su E4-193, la IA la comparó con la mía: la suya aportaba el campo
> **`Usuario.bloqueado`** (con migración y botón en la pantalla de roles) y la
> **validación de acceso** (`usuario_final` con perfil activo y no bloqueado), pero su
> flujo seguía hacia la operación digital y no restringía la navegación. Se integró su
> bloqueo, su validación y sus tests, adaptados a mis pantallas, con su commit
> conservado; se descartó su pantalla del kiosco. Resultado: 794 tests (31 del quiosco,
> 12 de restricción de sesión).

## 9. Contraste con la guía, el ERS y la API

> Prompt: (adjunté la API de Factura Segura, la guía de la cátedra y el ERS) "Analiza
> estos documentos y lo que solicita para el sprint número 5 que entrego el viernes."
> Después: "¿Todo lo necesario ya está en `develop`?"
>
> Resultado / Impacto: la IA contrastó cada criterio del Hito 7 con el repositorio real.
> El código del sprint estaba completo; lo que faltaba era el **tag de release** (`main`
> seguía en `v1.5.0`), los **CHIA**, la **planificación del Sprint 6** y ensayar el
> despliegue. Sobre la API encontró dos diferencias que **quedan declaradas acá**:
> - **no implementamos `dwn_kude` ni `dwn_xml`**: la API entrega el PDF oficial y el XML
>   firmado, y hoy el sistema descarga su propio PDF;
> - la **anulación usa nota de crédito, no `sol_cancelacion`**; es una decisión de diseño
>   válida pero distinta de la operación de cancelación de la API.
>
> Sobre el ERS, anotó que el punto 2.1.3 dice que el sistema no recibe facturas pero
> RF112 pide recibirlas (a aclarar con la cátedra), y que **RF110** (mostrar el número de
> atención al cliente) **sigue sin implementarse**.

## 10. Revisar los cambios de Romina sobre notificaciones

> Prompt: "Romina realizó modificaciones, ¿puedes ver si está todo correcto?"
>
> Resultado / Impacto: Romina quitó el **umbral del 1%** de las notificaciones de cambio
> de tasa, pedido por la profesora (ahora cualquier cambio real avisa). La IA encontró que
> su rama **dejaba dos tests en rojo**: eran dos tests míos de E4-32 que seguían
> afirmando "una variación chica no avisa", y ella solo había actualizado uno. Se
> actualizaron para afirmar el comportamiento nuevo (commit separado, el de ella
> conservado con su autoría) y la suite pasó a 795. También verificó que **todas** las
> vías de cambio de cotización (API, crear, editar, activar) disparan el aviso y el
> correo, así que si el correo "no llega", la causa es de configuración (`EMAIL_BACKEND`
> en el `.env`) y no de código. Al escribir este CHIA, el sondeo de notificaciones cada 5
> segundos sigue sin cambiar.

## 11. Errores de la IA y cómo se corrigieron

- **Duplicar el trabajo de Romina:** la IA construyó el quiosco sin esperar su push; al
  aparecer su rama hubo que integrar lo suyo en lugar de elegir una sola versión. Lo
  había advertido, pero igual costó una pasada extra de integración.
- **Rol `terminal` innecesario:** primero se creó un rol de Keycloak `terminal`; al
  probar el login, ese rol dejaba a la sesión en un 403. Se **eliminó** y alcanzó con
  la marca de sesión.
- **`makemigrations` generó "quitar y agregar" en vez de renombrar** el campo `numero`;
  se reescribió la migración como `RenameField` y se probó sobre una base de prueba.
- **Una prueba mal supuesta:** el test de compra asumía el flujo equivocado (el cliente
  paga guaraníes y recibe dólares); se corrigió el test, no el código.
- **Una fecha inválida rompía una vista** (`2026-99-99` lanzaba `ValueError`); se agregó
  la validación.
- **Tests que usaban `ANULADA` como "no emitida"** (los de Eva) y **una factura vieja en
  memoria** en un test: se cambió el estado usado y se refrescó el objeto.
- **Comandos de git en zsh:** `git show $RAMA:archivo` se rompía porque zsh interpreta
  `:archivo` como un modificador; se usó `${RAMA}:archivo`. Pasó más de una vez.
- **Citar un archivo que no existe:** al preparar este CHIA se iba a nombrar `pdf.py`,
  que ya no existe tras la integración (el PDF lo genera `services.py` de Eva); se
  detectó al verificar cada ruta citada.
- **Mensajes demasiado largos:** pedí que los mensajes para mis compañeras fueran
  cortos y solo con lo que tenían que hacer; la IA tendía a explicar de más.
- **Decisión mía:** no completar los CHIA de Eva ni de Eduardo (son suyos).

## 12. Archivos / evidencia

- Código: `apps/pasarela/stripe_pago.py`, `apps/facturacion/` (`emision.py`,
  `proveedores.py`, `services.py`, `models.py`, `management/commands/procesar_facturas.py`),
  `apps/caja/views_terminal.py`, `apps/caja/services.py`, `apps/usuarios/middleware.py`,
  `apps/usuarios/sesion.py`, `apps/usuarios/oidc.py`, `apps/usuarios/inactividad.py`,
  migraciones `facturacion/0002` a `0005` y `transacciones/0006`.
- Tests: `apps/facturacion/test_emision.py` (55), `test_nota_credito.py` (28),
  `apps/caja/test_quiosco.py` (31), `apps/caja/test_anulacion.py` (20),
  `apps/usuarios/test_modo_terminal.py` (12), `apps/pasarela/tests.py` (65, con los de
  Stripe).
- Documentación: `docs/facturacion.md`, `docs/produccion.md`, `docs/caja.rst`.
- PR: #62 (integración del sprint a `develop`).
- Resultado: **505 tests al cerrar el Sprint 4 y 795 en este momento**, con Sphinx en
  `-W` sin advertencias y el CI en verde en `develop`.
- **Sin verificar:** la API real de Factura Segura (no hay token) y un recorrido completo
  del quiosco con el login real de Keycloak y la factura llegando al correo (se probó
  con sesión forzada sobre el sistema en marcha y con tests).
