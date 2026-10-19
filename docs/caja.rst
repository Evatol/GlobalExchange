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
La simulación visible para la demo está en ``/api/caja/autoservicio/<id>/``; la
acción ``POST /api/caja/terminales/<id>/iniciar-operacion/`` aplica la misma
validación del lado del servidor.

Las cajas vinculadas a terminales no aparecen en la administración de cajas
de cajero: su inventario y su estado operativo se gestionan desde la terminal.

Acceso del usuario a la terminal (E4-193)
-----------------------------------------

La ruta ``/api/caja/autoservicio/<id>/`` es el kiosco público. Permite consultar
las tasas vigentes y simular conversiones sin autenticar; una simulación no crea
una transacción de compra o venta. Para operar, la persona inicia sesión en
Keycloak desde ``/api/caja/autoservicio/<id>/operar/``.

Antes de continuar se exige el rol ``usuario_final``, un perfil de negocio
activo y desbloqueado, y al menos un cliente activo asociado. Con un cliente se
selecciona automáticamente; con varios, la pantalla solicita una elección y
valida que pertenezca al usuario. Los bloqueos de operación se administran por
un administrador en la pantalla ``/api/usuarios/roles/`` y son independientes
del estado de autenticación de Keycloak. Un rechazo de autorización devuelve
HTTP 403 con un mensaje explicativo.

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

Module contents
---------------

.. automodule:: apps.caja
   :members:
   :show-inheritance:
   :undoc-members:
