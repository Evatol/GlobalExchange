# Guía de desarrollo — GlobalExchange

Cómo dejar el proyecto funcionando en tu máquina para trabajar en el **Sprint 2**.

> Para el Sprint 2 (Monedas, Cotizaciones, medios de pago, simulador, visualización)
> **NO hace falta Keycloak** ni el App Password de Gmail. Solo Python + PostgreSQL.
> El login por Keycloak se prueba aparte, al final del sprint.

---

## 1. Requisitos

Instalar (una vez):

- **Python 3.12 o 3.13** — https://www.python.org/downloads/
- **PostgreSQL 14 o superior** — https://www.postgresql.org/download/
  (durante la instalación te pide una contraseña para el usuario `postgres`; anotala)
- **Git** — https://git-scm.com/downloads

---

## 2. Crear la base de datos

Abrí una terminal y creá una base llamada **`Global_Exchange`**:

```bash
# Linux / Mac
sudo -u postgres createdb Global_Exchange

# Windows (PowerShell, desde la carpeta bin de PostgreSQL, o con psql en el PATH)
createdb -U postgres Global_Exchange
```

Si preferís interfaz gráfica: abrí **pgAdmin** → botón derecho en "Databases" → Create → Database → nombre `Global_Exchange`.

---

## 3. Bajar el proyecto

```bash
git clone https://github.com/Evatol/GlobalExchange.git
cd GlobalExchange
git checkout develop
```

---

## 4. Entorno de Python e instalar dependencias

**Linux / Mac:**
```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
```

> En el resto de la guía, donde diga `venv/bin/python`, en Windows usá `venv\Scripts\python`.

---

## 5. Configuración de la base (solo si hace falta)

El proyecto por defecto se conecta a PostgreSQL con:
usuario `postgres`, contraseña `123456`, host `localhost`, puerto `5432`.

**Si tu PostgreSQL usa OTRA contraseña**, creá un archivo llamado `.env` en la raíz del
proyecto (al lado de `manage.py`) con esto:

```
DB_NAME=Global_Exchange
DB_USER=postgres
DB_PASSWORD=TU_CONTRASEÑA_DE_POSTGRES
DB_HOST=localhost
DB_PORT=5432
```

El archivo `.env` **no se sube a git** (está ignorado). Si tu contraseña es `123456`,
no hace falta crearlo.

---

## 6. Preparar la base y crear un usuario administrador

```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py createsuperuser
```

En `createsuperuser` te pide usuario, email y contraseña — inventá algo que te acuerdes,
es solo para tu máquina.

---

## 7. Levantar el proyecto y verificar

```bash
venv/bin/python manage.py runserver 127.0.0.1:8000
```

Dejá esa terminal abierta. Abrí el navegador en:

- **http://127.0.0.1:8000/admin/** → entrá con el usuario que creaste en el paso 6.
  Deberías ver el panel de administración con Clientes, Monedas, Métodos de pago, etc.

En **otra terminal**, corré los tests:

```bash
venv/bin/python manage.py test
```

Tiene que terminar en **`OK`** (36 tests).

> **Si algo falla en los pasos 6 o 7, avisá en el grupo ANTES de empezar a programar.**

---

## 8. Empezar a trabajar tu historia

1. Actualizá `develop` y creá tu rama:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/E4-XXX-descripcion-corta
   ```
   (reemplazá `E4-XXX` por el número de tu historia en Jira)

2. Programá tu parte. Si tocás modelos, generá la migración:
   ```bash
   venv/bin/python manage.py makemigrations
   venv/bin/python manage.py migrate
   ```

3. Escribí tests en el `tests.py` de tu app y corré `manage.py test` seguido.

4. Subí tus cambios:
   ```bash
   git add .
   git commit -m "E4-XXX: descripcion de lo que hiciste"
   git push -u origin feature/E4-XXX-descripcion-corta
   ```

5. En GitHub, abrí un **Pull Request** de tu rama hacia `develop`.
   El CI corre los tests automáticamente. Si queda verde ✅, se mergea.

### Reglas para no pisarnos

- Cada uno en su carpeta: `apps/divisas` (Eva, Eduardo, Romina), `apps/transacciones`
  y `apps/usuarios` (Angel).
- `apps/usuarios` la comparte todo el equipo → **avisá en el grupo antes de tocarla.**
- PRs chicos y frecuentes, no un merge gigante al final.
- Todos los días, antes de arrancar: `git pull origin develop`.

---

## Problemas comunes

| Error | Solución |
|---|---|
| `could not connect to server` / `Connection refused` (5432) | PostgreSQL no está corriendo. Arrancá el servicio de PostgreSQL. |
| `password authentication failed for user "postgres"` | La contraseña no coincide → creá el `.env` del paso 5 con tu contraseña real. |
| `database "Global_Exchange" does not exist` | Faltó el paso 2 (crear la base). |
| `ModuleNotFoundError` al correr `manage.py` | No activaste el venv o faltó `pip install -r requirements.txt`. |
| En Windows, `venv\Scripts\Activate.ps1 ... no se puede cargar` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y reintentá. O usá directamente `venv\Scripts\python manage.py ...` sin activar. |

---

## Qué NO necesitás para el Sprint 2

- ❌ Keycloak (el contenedor Docker)
- ❌ App Password de Gmail
- ❌ Los comandos `configure_keycloak_*`
- ❌ El archivo `.env.backup`

Todo eso es para el flujo de login/autoregistro, que se prueba por separado.
