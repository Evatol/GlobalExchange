# Registro de Pruebas Unitarias y Documentación de Código Fuente

Este documento registra, por fecha y por artefacto (módulo/app), el avance de
pruebas unitarias y de documentación de código fuente a lo largo de los
sprints, según lo pedido para la revisión (PUD). Los datos surgen del
historial real de Git (`git log`, `git diff`) del repositorio, no son
estimados.

Para reproducir cualquier cifra de este documento:

```
git show --name-status --format="%ad %h %s" --date=short <hash>
```

---

## 1. Pruebas Unitarias

### Sprint 1 (Hito 3)

| Fecha | Commit | Artefacto | Detalle | Tests nuevos | Acumulado | Autor |
|---|---|---|---|---:|---:|---|
| 2026-08-30 | `cbf6a83` | `apps/usuarios` (Cliente) | CRUD de Clientes con segmentación (E4-125/E4-124) | +18 | 18 | Angel |
| 2026-09-05 | `63a9b6a` | `apps/usuarios` (Cliente↔Usuario) | Endpoints dedicados de asignación usuario/cliente (RF42) | +6 | 24 | Angel |
| 2026-09-05 | `ba5ef49` | `apps/usuarios` (backends/oidc) | Roles de Keycloak reflejados en Django, bloqueo y recuperación por Keycloak (E4-120) | +9 | 33 | Angel |
| 2026-09-06 | `9b31f9c` | `apps/usuarios` (alta por admin) | Alta de usuario por el administrador con envío de credenciales (RF1-RF3) | +3 | 36 | Angel |

**Cierre de Sprint 1 (tag `v1.2.0`): 36 tests.**

### Sprint 2 (Hito 4)

| Fecha | Commit | Artefacto | Detalle | Tests nuevos | Acumulado | Autor |
|---|---|---|---|---:|---:|---|
| 2026-09-08 | `2dd9a40` | `apps/divisas` (Moneda) | CRUD de Monedas con borrado lógico (activar/desactivar) | +6 | 42 | Eva Torres |
| 2026-09-10 | `ff7862f` | `apps/divisas` (Moneda) | Filtros y docstring del CRUD de Monedas (E4-137) | +2 | 44 | Angel |
| 2026-09-10 | `791f9cd` | `apps/divisas` (TasaCambio/Simulacion) | Tasas públicas y simulador de conversión | +4 | 48 | Romina Pérez |
| 2026-09-10 | `ba8e73f` | `apps/divisas` (Cotizacion→TasaCambio) | CRUD de Cotizaciones reconstruido sobre `TasaCambio` (E4-26), reemplaza un modelo duplicado sin tests | +9 | 57 | Angel |
| 2026-09-10 | `ff2513c` | `apps/transacciones` (MedioPagoCliente) | CRUD de métodos de pago y medios de pago del cliente (RF17) | +10 | 67 | Angel |
| 2026-09-10 | `eb4ec7a` | `apps/usuarios` (sesión) | Selector de cliente activo (E4-130/RF43) | +9 | 76 | Angel |
| 2026-09-11 | `2fd2cdf` | `apps/divisas` (vista pública) | Pantalla pública de cotizaciones vía Keycloak (corrección de login/logout y reuso de lógica) | +8 | 84 | Angel |

**Estado actual de Sprint 2: 84 tests (+48 desde el cierre de Sprint 1).**

Verificación: `python manage.py test` → `Ran 84 tests ... OK`.

### Sprint 3 (Hito 5)

Cierre al tag `v1.4.0` (2026-10-01): **201 tests**. Las filas posteriores son
mejoras hechas en `develop` después del tag (ver la guía de revisión).

| Fecha | Commit | Artefacto | Detalle | Tests nuevos | Acumulado | Autor |
|---|---|---|---|---:|---:|---|
| 2026-09-11 | `18a9cec` | `apps/usuarios` (roles) | Administración de roles por el administrador (RF44/RF46/RF48) | +11 | 95 | Angel |
| 2026-09-11 | `b21632a` | `apps/divisas`, `transacciones`, `usuarios` | Permisos DRF por rol y menú dinámico (RF21/RF22/RF44) | +20 | 115 | Angel |
| 2026-09-11 | `2dcb87e` | `apps/divisas`, `transacciones` | Pantallas propias de Monedas, Cotizaciones, Métodos y Medios de pago | +15 | 130 | Angel |
| 2026-09-12 | `8f4bb9a` | `apps/usuarios` (Cliente) | Pantalla de gestión de clientes con asociación de usuarios | +6 | 136 | Angel |
| 2026-09-12 | `b9ea10f` | `apps/usuarios` (Cliente) | Editar los datos de un cliente existente | +5 | 141 | Angel |
| 2026-09-12 | `32875e3` | `apps/divisas`, `transacciones` | "Editar" en Monedas, Cotizaciones, Métodos y Medios de pago | +9 | 150 | Angel |
| 2026-09-12 | `e4e1da0` | `apps/usuarios` (perfil) | "Mi Perfil": autoactualización de datos personales (RF9/RF10) | +6 | 156 | Angel |
| 2026-09-12 | `5642a11` | `apps/usuarios` (perfil) | Cambio de contraseña desde Mi Perfil (RF9) | +1 | 157 | Angel |
| 2026-09-12 | `0b94757` | `apps/usuarios` (perfil) | Cambio de contraseña sin salir de la aplicación (RF9) | +10 | 167 | Angel |
| 2026-09-20 | `172391c` | `apps/transacciones` | Compra y venta de divisas (E4-19/E4-20/E4-144) | +14 | 181 | Angel |
| 2026-09-18 | `8a9bb70` | `apps/transacciones` | Cancelación automática por cambio de tasa (E4-28) | +2 | 183 | Romina Pérez |
| 2026-09-20 | `71e4ea9` | `apps/transacciones` | Tests del historial y su exportación (E4-104/E4-36) | +8 | 191 | Angel |
| 2026-09-23 | `3c491dd` | `apps/transacciones` | Límites de compra/venta por cliente (E4-143) | +6 | 197 | Angel |
| 2026-09-24 | `8ba81cf` | `apps/transacciones` | Montos redondeados a 2 decimales | +1 | 198 | Angel |
| 2026-09-24 | `c353365` | `apps/usuarios` (seed demo) | Un solo comando para levantar todo el sistema | +3 | 201 | Angel |

**Cierre de Sprint 3 (tag `v1.4.0`): 201 tests.**

Mejoras posteriores al tag, en `develop`:

| Fecha | Commit | Artefacto | Detalle | Tests nuevos | Acumulado | Autor |
|---|---|---|---|---:|---:|---|
| 2026-10-04 | `b892ead` | `apps/transacciones` | Confirmar el pago desde la pantalla y cancelar a pedido (E4-28, RF23) | +10 | 211 | Angel |
| 2026-10-04 | `5797243` | `apps/divisas`, `transacciones` | Tasa cruzada de la pizarra aplicada al cliente (+6 nuevos, 1 reemplazado) | +5 | 216 | Angel |
| 2026-10-05 | `bbb4025` | `apps/divisas`, `transacciones` | Mensaje claro para medio de pago repetido y API cerrada por defecto | +4 | 220 | Angel |
| 2026-10-09 | `22551e4` | `apps/banco` (nueva) | Banco simulado: cuentas, billeteras y tarjetas, movimientos, API y permisos | +27 | 247 | Angel |
| 2026-10-09 | `5dcd6a6` | `apps/usuarios` (Cliente) | Categoría Minorista/Mayorista/VIP fija el límite por operación (2 tests reemplazados) | +0 | 247 | Angel |
| 2026-10-09 | `e79718b` | `apps/divisas` | "Cambio del Día" compartido y cotización vigente por moneda | +2 | 249 | Angel |
| 2026-10-09 | `700f108` | `apps/transacciones` | Pago con banco, operaciones fallidas, tarjeta solo en compras, cambio entre divisas (+42 nuevos, 6 reemplazados) | +36 | 285 | Angel |
| 2026-10-09 | `51f1834` | `apps/divisas` | La calculadora pública y el simulador por API convierten entre divisas | +7 | 292 | Angel |

**Estado actual de Sprint 3: 292 tests (+208 desde el cierre de Sprint 2).**

Verificación: `./scripts/pruebas.sh` → `Ran 292 tests ... OK`. Cada cifra sale de
contar `def test_` agregados y quitados por commit (`git show <hash> -- 'apps/*/tests.py'`)
y coincide con las corridas reales: 220 antes del banco y 285 al mergear el PR #43.

### Sprint 4 (Hito 6)

Parte de los **292 tests** con los que cerró el Sprint 3. El "Acumulado" sigue el orden en
que cada historia se integró a `develop`.

| Fecha | Commit | Artefacto | Detalle | Tests nuevos | Acumulado | Autor |
|---|---|---|---|---:|---:|---|
| 2026-10-10 | `ecd4ede` | `apps/transacciones` (pago externo) | E4-157/E4-158: métodos `iniciar_pago_externo` y `confirmar_pago_webhook`; **sin tests ni endpoint** (se completó en `f1d39ea`) | +0 | 292 | Eduardo |
| 2026-10-09 | `51ecc5a` | `apps/usuarios` (favoritas) | Marcar monedas como favoritas (E4-24) | +2 | 294 | Romina Pérez |
| 2026-10-10 | `2c4bf26` | `apps/notificaciones` | Avisos de variación de cotización en tiempo real (E4-32) | +4 | 298 | Romina Pérez |
| 2026-10-10 | `5bb0648` | `apps/notificaciones` | Aviso por correo de cambios de cotización (E4-33): extiende los tests de E4-32 en vez de crear nuevos | +0 | 298 | Romina Pérez |
| 2026-10-10 | `fb95b11` | `apps/caja` (sucursales) | Sucursales, asignación de cajeros (máx. 2) y rol cajero (E4-98) | +17 | 315 | Eva Torres |
| 2026-10-10 | `d8e5c7c` | `apps/caja` (billetes) | Inventario de billetes, denominaciones, cajas y arqueo (E4-99) | +28 | 343 | Eva Torres |
| 2026-10-10 | `f1d39ea` | `apps/transacciones` (webhook) | Webhook firmado, pago por la pasarela, sin doble cobro; completa E4-157/E4-158 | +25 | 368 | Angel |
| 2026-10-10 | `a07d445` | `apps/caja` (balance y cierre) | Balance y cierre de caja, mostrador y registro automático de billetes (E4-100/E4-101); incluye los tests de la operación presencial de E4-99, que no los tenía | +54 | 422 | Angel |
| 2026-10-10 | `3156b41` | `apps/usuarios` (seed demo) | Rol cajero, `cajero_demo` y caja demo abierta | +4 | 426 | Angel |
| 2026-10-10 | `f249cae` | `apps/notificaciones` | Los avisos se marcan como leídos al cerrarlos y aparecen también en Operar | +10 | 436 | Angel |
| 2026-10-10 | `718d58a` | `apps/pasarela` (nueva) | Pasarela de pago simulada con pantalla de pago, sin comandos (E4-157/E4-158) | +16 | 452 | Angel |
| 2026-10-10 | `6f395ad` | `apps/notificaciones` | Editar la cotización vigente también avisa (E4-32/E4-33) | +8 | 460 | Angel |

**Estado actual de Sprint 4: 460 tests (+168 desde el cierre de Sprint 3).**
El cierre del sprint (tag `v1.5.0`) se completa al ponerlo.

Verificación: `./scripts/pruebas.sh` → `Ran 460 tests ... OK`. Cada cifra sale de contar los
`def test_` de cada commit contra su commit padre (`git show <hash>`); coincide con las
corridas reales: 343 al integrar a Romina y Eva, 426 al mergear el PR #48 y 452 con la
pasarela (PR #50). Los merges conservan los tests de las dos ramas que unen (revisado uno
por uno).

---

## 2. Documentación de Código Fuente (Sphinx / PDO)

### Sprint 1 (Hito 3)

| Fecha | Commit | Artefacto | Detalle | Autor |
|---|---|---|---|---|
| 2026-08-28 | `e213b9a` | Todas las apps | Configuración inicial de generación automática de documentación (Sphinx autodoc, un `.rst` por app) | Romina Pérez |
| 2026-09-05 | `08c6be6` | Todas las apps, `conf.py` | Reproducibilidad desde un clon limpio: se corrige el `sys.path` que rompía la resolución de `app_label` de Django; se agrega `requirements-dev.txt` | Angel |
| 2026-09-05 | `6d34ee7` | `index.rst` | Se vinculan todas las apps en el índice de la documentación | Romina Pérez |

### Sprint 2 (Hito 4)

| Fecha | Commit | Artefacto | Detalle | Autor |
|---|---|---|---|---|
| 2026-09-11 | `2fcd16b` | `divisas.serializers`, `transacciones.serializers`, `usuarios.sesion` | Entradas `.rst` faltantes para los módulos nuevos del sprint; se reactiva el job de CI que compila la documentación (diagnosticado y corregido el crash de `autodoc` en Python 3.13) | Angel |

Verificación: `sphinx-build -b html -W --keep-going docs docs/_build/html` → `build succeeded`, sin warnings.

### Sprint 3 (Hito 5)

| Fecha | Commit | Artefacto | Detalle | Autor |
|---|---|---|---|---|
| 2026-09-11 | `b21632a` | `usuarios.permissions` | Entradas `.rst` del módulo de permisos por rol | Angel |
| 2026-10-09 | `22551e4` | `banco` (nueva app) | Páginas `banco.rst` y `banco.migrations.rst` (modelos, servicios, serializers, vistas y tests) enlazadas en el índice | Angel |
| 2026-10-09 | `ac8d7d8` | `banco.serializers` | Docstring propio en `CuentaBancariaSerializer.create`: el heredado de DRF (`**validated_data`) hacía fallar el build con `-W` en el CI | Angel |

Nota: `sphinx-build` consulta la base de datos (autodoc hace `repr()` de los
`queryset` de los ViewSets), así que la base tiene que estar migrada. En el CI
se migra antes del build.

Verificación: mismo comando → sin warnings.

### Sprint 4 (Hito 6)

| Fecha | Commit | Artefacto | Detalle | Autor |
|---|---|---|---|---|
| 2026-10-10 | `f1d39ea` | `transacciones.webhook` | Módulo de firma del webhook (E4-158) | Angel |
| 2026-10-10 | `a07d445` | `caja.services`, `caja.serializers`, `caja.serializers_billetes`, `caja.views_billetes`, `caja.views_pantallas` | Los módulos de caja (E4-98/99/100/101) no figuraban en la documentación | Angel |
| 2026-10-10 | `f249cae` | `divisas.services`, `usuarios.middleware` | Módulos de E4-32/33 y E4-98 que no figuraban | Angel |
| 2026-10-10 | `718d58a` | `pasarela` | App nueva: `apps`, `urls`, `views` y `tests` | Angel |
| 2026-10-10 | `919bb84`, `f1d39ea` | Docstrings de `divisas.views`, `transacciones.models`, `transacciones.views` | Se restauraron 35 docstrings que habían borrado las ramas de E4-24/32/33 y E4-157/158 al integrarse (7 + 28; solo docstrings, la lógica no cambia) | Angel |

Verificación: `sphinx-build -b html -W --keep-going docs docs/_build/html` → sin warnings,
con todos los módulos de las apps de negocio incluidos (se revisó que no quede ninguno sin
entrada).

---

## 3. Cómo reproducir estas cifras

```bash
# Pruebas unitarias (total y por app)
python manage.py test
python manage.py test apps.divisas apps.transacciones apps.usuarios

# Documentación (build limpio, falla si hay warnings)
pip install -r requirements-dev.txt
sphinx-build -b html -W --keep-going docs docs/_build/html
```

Ambos pasos corren también en CI (`.github/workflows/ci.yml`) en cada push
y pull request a `develop`/`main`.

> Este documento se actualiza al cierre de cada sprint, agregando las filas
> correspondientes al sprint recién cerrado.
