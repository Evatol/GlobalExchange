caja package
============

Terminales de autoservicio
--------------------------

La administración de terminales se encuentra en ``/api/caja/gestion/terminales/``
y está disponible para administradores. Al dar de alta una terminal se crea,
en una transacción, su caja propia y el stock inicial por denominación. Las
cantidades omitidas comienzan en cero. Las denominaciones deben estar activas
y la sucursal debe estar activa.

Los estados posibles son ``ACTIVA``, ``INACTIVA`` y ``MANTENIMIENTO``. La baja
es lógica y conserva la caja y sus movimientos. Una terminal en estado no
operativo, o ubicada en una sucursal inactiva, no puede iniciar operaciones.
La pantalla de cada terminal está en ``/api/caja/autoservicio/<id>/`` (desde
Terminales, botón *Abrir*); la acción
``POST /api/caja/terminales/<id>/iniciar-operacion/`` aplica la misma validación
del lado del servidor.

Ingresar y operar en la terminal (E4-193, E4-194)
-------------------------------------------------

El recorrido del cliente en el quiosco es:

1. **Inicio** (pública, sin iniciar sesión): cotizaciones del día vistas desde el
   cliente (*comprás a* / *vendés a*) y la calculadora de divisas. Si la terminal no
   está activa, o su sucursal está inactiva, avisa que no está operativa (HTTP 409) y no
   deja avanzar.
2. **Identificación**: el botón *Identificarme para operar* lleva al login de Keycloak y
   vuelve a ``/api/caja/autoservicio/<id>/ingreso/``. Desde ahí la sesión queda marcada
   como de terminal (``terminal_id`` en la sesión) y
   ``TerminalSoloAutoservicioMiddleware`` responde **403** a cualquier pantalla que no
   sea del autoservicio, del login/logout (``/oidc/``) o de las cotizaciones públicas.
   Solo opera un usuario con rol ``usuario_final`` y perfil activo y no bloqueado
   (``Usuario.bloqueado``, que un administrador cambia en ``/api/usuarios/roles/`` sin
   tocar Keycloak); si no cumple, ve el motivo con un **403**. Se revisa en cada pantalla,
   así que un bloqueo hecho durante la sesión corta la operación.
3. **Cliente**: si el usuario tiene un solo cliente activo se usa ese; si tiene varios,
   elige uno; si no tiene ninguno (o todos están dados de baja) se le explica y solo puede
   salir.
4. **Operar** (``/operar/``): compra, venta o cambio, **solo en efectivo**. *Calcular*
   muestra tasa, comisión, total y los billetes que el cliente tiene que ingresar y los
   que la terminal le entrega, y valida el límite por operación de la categoría del
   cliente. Si con el stock de la terminal no se puede completar, lo avisa y no ofrece
   confirmar. *Confirmar operación* la registra en el acto sobre la **caja de la
   terminal** (modalidad ``TERMINAL``): queda ``EXITOSA`` con sus movimientos de billetes
   y su factura electrónica, que se envía al correo del usuario.
5. **Comprobante**: resultado y desglose de billetes. Desde ahí, *Nueva operación* o
   *Terminar y salir*.

Si al confirmar falla el stock de la terminal, el límite de la categoría o cambió la
cotización, **no se mueve ningún billete** y el intento queda registrado como ``FALLIDA``
(con el motivo en la observación); el cliente ve el mensaje y el número del intento.

*Salir* (o el cierre por inactividad) cierra la sesión de Django y la de Keycloak y vuelve
al inicio de la terminal, lista para el siguiente cliente.

Las cajas vinculadas a terminales no aparecen en la administración de cajas
de cajero: su inventario y su estado operativo se gestionan desde la terminal.

Subpackages
-----------

.. toctree::
   :maxdepth: 4

   caja.migrations

Submodules
----------

caja.admin module
-----------------

.. automodule:: apps.caja.admin
   :members:
   :show-inheritance:
   :undoc-members:

caja.apps module
----------------

.. automodule:: apps.caja.apps
   :members:
   :show-inheritance:
   :undoc-members:

caja.models module
------------------

.. automodule:: apps.caja.models
   :members:
   :show-inheritance:
   :undoc-members:

caja.serializers module
-----------------------

.. automodule:: apps.caja.serializers
   :members:
   :show-inheritance:
   :undoc-members:

caja.serializers_billetes module
--------------------------------

.. automodule:: apps.caja.serializers_billetes
   :members:
   :show-inheritance:
   :undoc-members:

caja.services module
--------------------

.. automodule:: apps.caja.services
   :members:
   :show-inheritance:
   :undoc-members:

caja.tests module
-----------------

.. automodule:: apps.caja.tests
   :members:
   :show-inheritance:
   :undoc-members:

caja.urls module
----------------

.. automodule:: apps.caja.urls
   :members:
   :show-inheritance:
   :undoc-members:

caja.views module
-----------------

.. automodule:: apps.caja.views
   :members:
   :show-inheritance:
   :undoc-members:

caja.views_billetes module
--------------------------

.. automodule:: apps.caja.views_billetes
   :members:
   :show-inheritance:
   :undoc-members:

caja.views_pantallas module
---------------------------

.. automodule:: apps.caja.views_pantallas
   :members:
   :show-inheritance:
   :undoc-members:

caja.views_terminal module
--------------------------

.. automodule:: apps.caja.views_terminal
   :members:
   :show-inheritance:
   :undoc-members:

Module contents
---------------

.. automodule:: apps.caja
   :members:
   :show-inheritance:
   :undoc-members:
