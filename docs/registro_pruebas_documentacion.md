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
