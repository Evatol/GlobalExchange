# Guía de Revisión — Hito 5 / Sprint 3

Tener esta guía abierta en una pantalla aparte durante la revisión. La
profesora dirige: saltá directo a la sección que pida.

**Cómo se presenta este sprint.** El tag `v1.4.0` es la entrega del viernes
1/10 y no se modifica. Las mejoras posteriores están en `develop` y se presentan
desde ahí, con la autorización de la cátedra. Primero se muestra el tag;
después se pasa a `develop`.

Los números de esta guía son los que salen con los datos de demostración:
USD a 7.300 (compra) / 7.400 (venta), y `cliente_demo` operando sobre
"Comercial Uno" (mayorista, 0,5% de comisión, límite de compra 100.000).

---

## 0. Antes de que llegue la profe (10 minutos antes)

1. Docker andando: `docker info`.
2. Liberar los puertos, por si quedó algo corriendo:
   `docker stop keycloak-dev` y `pkill -f 'manage.py runserver'`.
3. Actualizar `develop` (**obligatorio**: si tu `develop` local está atrasado, el
   script de la presentación todavía es la versión vieja y no conoce la
   opción `--presentacion`):

   ```
   git checkout develop
   git pull origin develop
   ```

4. Hacer **una vez** los pasos 1 y 2 de abajo. La primera vez Keycloak tarda
   en arrancar; después, frente a la profe, tarda segundos.
5. Abrir dos ventanas del navegador: una **normal** (cliente) y una
   **privada** (analista).

---

## 1. SCC — "Pónganse en el tag"

```
cd ~/Escritorio/IS2/GlobalExchange
./scripts/verificar_tag.sh v1.4.0
```

Tiene que terminar con `OK: el repositorio está parado en el tag 'v1.4.0'.`

El aviso amarillo de *detached HEAD* **no es un error**: significa que estás
parado en un commit fijo y no en una rama, que es justo lo que se pide
demostrar.

Los tags del proyecto: `v1.0.0`, `v1.1.0`, `v1.2.0` (Sprint 1), `v1.3.0`
(Sprint 2), `v1.4.0` (Sprint 3).

## 2. Pasar a `develop` con las mejoras y levantar el sistema

```
git checkout develop && ./scripts/levantar_sistema.sh --presentacion
```

El `git checkout develop` hay que tipearlo: parado en el tag, los archivos son
los del viernes y el script todavía no tiene la opción `--presentacion`.
Desde `develop`, el script muestra y ejecuta:

```
$ git checkout develop
$ git pull --ff-only origin develop
$ git log --oneline v1.4.0..develop      <- todo lo hecho después de la entrega
```

y después levanta el sistema **en limpio** (borra los datos y arranca de
cero: la primera operación es la #1 y los números de esta guía coinciden
exactos). Termina con **SISTEMA LISTO**.

🗣️ *"El tag es lo entregado el viernes. Después de la entrega encontramos
dos errores y los corregimos: las tasas de compra y venta se aplicaban al
revés, y la cancelación por cambio de cotización no se podía ver en
pantalla. Presentamos desde develop con esas correcciones; esta lista es
exactamente lo que cambió."*

Todos los usuarios usan la contraseña `Demo1234!`.

| Usuario | Rol | Ve |
|---|---|---|
| `admin_demo` | administrador | todo, incluidos Roles y Métodos de Pago |
| `analista_demo` | analista | CRUD de Clientes, Monedas y Cotizaciones |
| `cliente_demo` | usuario final | Divisas, Mis Medios de Pago, Comprar/Vender, Historial |
| `angel` | **sin rol** | el menú básico; sirve para la demo de asignación de roles (sección 3) |

## 3. Asignación de roles (con `angel`)

1. **Ventana privada:** `angel` → el menú no tiene ningún CRUD. Si escribís
   `http://localhost:8000/api/divisas/gestion/monedas/`, responde 403.
2. **Ventana normal:** `admin_demo` → **Administración de Roles**: `angel`
   aparece **sin rol** → elegí **analista** → **Guardar**.
3. **Ventana privada:** **Cerrar Sesión** y volver a entrar como `angel`:
   ahora el menú tiene **CRUD Clientes, CRUD Monedas y CRUD Cotizaciones**.

🗣️ *"El rol vive en Keycloak, que es la fuente de verdad. Django lo toma en
el próximo login; por eso hay que volver a entrar para ver el cambio."*

---

## 4. PUD — Pruebas y documentación

```
./scripts/pruebas.sh
```

Termina con **`Ran 220 tests ... OK`**. Para ver solo las del sprint:

```
venv/bin/python manage.py test apps.transacciones -v 2
```

```
./scripts/documentacion.sh
xdg-open docs/_build/html/index.html
```

Compila con `-W`: cualquier warning la hace fallar, igual que el CI. Para
mostrar que la documentación sale del código, abrí el módulo
`transacciones.models` y buscá `Transaccion.confirmar`: su descripción es el
docstring del método.

---

## 5. ALC — Alcance del sprint

Entrá por la pantalla pública: `http://localhost:8000/` → **Ingresar al
Portal** → `cliente_demo`.

### 5.1 Compra y venta, con comisión y tasa aplicada

**Comprar/Vender Divisas** → Comprar, USD, **13**, Caja chica →
**Continuar al pago**.

```
Tasa aplicada ..................   7 400,00 PYG
Subtotal (13,00 × 7 400,00) ....  96 200,00 PYG
Comisión (0,50%, se suma) ......    + 481,00 PYG
Total a pagar ..................  96 681,00 PYG
```

**Confirmar pago** → *"Pago confirmado. La operación #1 se realizó con
éxito."*

🗣️ *"Si el cliente compra dólares, la casa le vende a su tasa de venta. La
comisión depende de la categoría del cliente: Comercial Uno es mayorista y
paga 0,5%."*

**Venta:** **Nueva operación** → Vender, USD, **13** → **Continuar al pago**:
13 × 7.300 = 94.900,00 − 474,50 → **Total a recibir 94.425,50** →
**Confirmar pago**.

🗣️ *"Compró a 96.681 y vendió a 94.425,50: la diferencia queda para la
casa, como en una casa de cambio real."*

**Límite del cliente:** Comprar **14** USD → *"El monto de la operación
(104118.00) supera el límite de compra configurado para el cliente
(100000.00)."* No se crea ninguna operación.

**Opcional, la diferencia entre categorías:** como `admin_demo`, en CRUD
Clientes, asociá `cliente_demo` a "Comercial Dos" (estándar, 1,5%). Como
cliente, elegí Comercial Dos en el selector de arriba, cargá un medio de
pago y comprá 13 USD: **97.643,00** (comisión 1.443,00, el triple).

### 5.2 Cancelación por cambio de cotización antes del pago (E4-28)

1. **Ventana normal (cliente):** Comprar, USD, **13** → **Continuar al
   pago** → quedate en el resumen **sin confirmar**.
2. **Ventana privada (analista):** `analista_demo` → **CRUD Cotizaciones** →
   fila **USD** (no es la primera de la lista) → **Editar** →
   **7350 / 7450**.
3. **Ventana normal:** **Confirmar pago** → **Cancelada**: *"La transacción
   ha sido cancelada porque la tasa de cambio ha sufrido modificaciones (se
   inició a 7400.00 y la vigente es 7450.00)."*
4. Contraste: nueva compra de 13 USD → ahora el resumen dice **7.450** →
   **Confirmar pago** → Exitosa.
5. **Volvé USD a 7300 / 7400.** Si no, el resto de la demo da otros números.

🗣️ *"La operación guarda la tasa con la que se inició. Al confirmar el pago
se compara con la vigente: si cambió, se cancela sola."*

Además: **Cancelar operación** en el resumen la cancela a pedido del cliente
(RF23). Si el cliente se va sin pagar, la operación aparece en Comprar/Vender
→ "Operaciones pendientes de pago".

Los tests de esta lógica:

```
venv/bin/python manage.py test apps.transacciones.tests.ConfirmacionDePagoTests apps.transacciones.tests.TransaccionCancelacionPorCambioDeTasaTests -v 2
```

### 5.3 Historial de transacciones (solo consulta)

**Historial**: fecha, tipo, moneda, cantidad, tasa, total y estado. Filtrá
por estado **Cancelada** y exportá a **PDF**: el archivo respeta el filtro
aplicado. `cliente_demo` ve solo las operaciones de su cliente activo;
`admin_demo` ve todas.

---

## 6. CHIA

En `docs/`: `chia_sprint3_eva.md`, `chia_sprint3_eduardo.md`,
`chia_sprint3_romina.md` y `conversacion_ia_sprint3_angel.md`.

## 7. PLA

Jira: Sprint 3 con sus historias completadas y asignadas, y el Sprint 4
planificado.

## 8. QA

- CI en cada PR: pruebas unitarias (PUN) y documentación con `-W` (PDO).
- 220 tests, 86% de cobertura.
- Errores detectados y corregidos durante el sprint: un PR que se había
  mergeado sin funcionar, las tasas invertidas, una transacción cancelada que
  podía volver a confirmarse, montos con 8 decimales.
- La API está cerrada por defecto: solo las tasas, el simulador y los
  catálogos se leen sin login.

---

## 9. AMB — Ambiente de producción (dejarlo para el final)

Va al final porque producción reemplaza a desarrollo.

1. **Con desarrollo levantado**, abrí `http://localhost:8000/no-existe/`: la
   página amarilla de Django, con todo el detalle interno.
2. Levantá producción:

   ```
   ./scripts/levantar_sistema.sh --prod
   ```

3. Recargá la misma URL: ahora solo dice **"Not Found"**.
4. Verificación completa:

   ```
   ./scripts/verificar_produccion.sh
   ```

   Tiene que terminar con **"AMBIENTE DE PRODUCCIÓN OK: 11 verificaciones
   pasaron"**.

🗣️ *"Mismo código, dos ambientes: gunicorn, DEBUG apagado, estáticos con
WhiteNoise y una base de datos propia."*

Si pregunta por los tres avisos de `check --deploy`: son por no tener HTTPS
(no hay dominio ni certificado). Está documentado en `docs/produccion.md`; con
un certificado se activan por variable de entorno, sin tocar código.

Para volver a desarrollo:

```
docker compose -f docker-compose.prod.yml down
./scripts/levantar_sistema.sh
```

---

## 10. Preguntas que ya tenés respondidas

**"¿Por qué presentan desde develop y no desde el tag?"**
Porque después de la entrega corregimos dos errores, y la cátedra autorizó
presentar con las mejoras. El tag del viernes no se tocó: está para comparar,
y `git log --oneline v1.4.0..develop` muestra exactamente qué cambió.

**"¿Por qué la tasa de compra se aplica a la venta?"**
La pizarra muestra las tasas desde el punto de vista de la casa: a cuánto
compra y a cuánto vende. Cuando el cliente compra, la casa vende, y al
revés. La regla está en un solo lugar: `TasaCambio.tasa_para()`.

**"¿Por qué el puerto de Postgres no está publicado?"**
Django le habla por la red interna de Docker. Publicarlo solo servía para
chocar con el PostgreSQL local de cada integrante. Para entrar a la base:
`docker compose exec postgres psql -U postgres Global_Exchange`.

**"¿Por qué hay dos URLs de Keycloak?"**
El navegador y el contenedor de Django lo ven distinto: `KEYCLOAK_SERVER_URL`
(`http://keycloak:8080/`) es la interna y `KEYCLOAK_PUBLIC_URL`
(`http://localhost:8080/`) es a la que se redirige el navegador.

**"¿Y la verificación por correo del autoregistro?"**
Está implementada (`./scripts/levantar_sistema.sh --con-correo`). Necesita el
App Password de Gmail, que no está en el repositorio porque es público: cada
integrante lo pone en su `.env`, que git ignora.

---

## 11. Si algo falla en vivo

| Problema | Solución |
|---|---|
| "Puertos ocupados" | `docker compose down` y de nuevo `./scripts/levantar_sistema.sh` |
| El login no pide credenciales | estás en una ventana con una sesión vieja: usá la privada |
| Los números no coinciden | USD quedó distinto de 7300 / 7400: corregilo en CRUD Cotizaciones |
| Se cayó Docker | `docker compose down` y `./scripts/levantar_sistema.sh` (los datos están en volúmenes) |

## 12. Ensayo recomendado (una vez antes de la revisión)

1. `./scripts/verificar_tag.sh v1.4.0`
2. `git checkout develop && ./scripts/levantar_sistema.sh --presentacion`
3. Asignarle un rol a `angel` (3) y compra de 13 USD con confirmación de pago (5.1)
4. Cancelación por cambio de cotización, con las dos ventanas (5.2)
5. Historial con filtro y exportación (5.3)
6. `./scripts/pruebas.sh` y `./scripts/documentacion.sh`
7. Producción y `./scripts/verificar_produccion.sh` (9)

Si los siete pasos te salen sin leer la guía, estás listo.
