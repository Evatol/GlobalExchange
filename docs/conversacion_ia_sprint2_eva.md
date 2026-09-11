Registro de Conversaciones con IA (CHIA) - Sprint 2

*Integrante: EVA TORRES (CRUD de Monedas - Módulo Divisas)
*Rol / Epic: Epic 8 - Configuración y Administración del Sistema (Ticket E4-137)
*Fecha: Agosto 2026

---

## 1. Resumen de Interacciones

Instalación y verificación de PostgreSQL (vía pgAdmin), creación de la base Global_Exchange, clonado del repositorio, actualización de la rama develop (incorporando el tag v1.2.0), instalación de dependencias con pip y configuración del entorno virtual .venv en Windows.

Verificación del proyecto base: migración de la base de datos, creación de superusuario, levantamiento del servidor Django y validación de los 36 tests originales del proyecto (estado OK).

Implementación del CRUD de Monedas (RF102): desarrollo de serializer.py, views.py (ViewSet con borrado lógico) y urls.py del módulo apps/divisas, respetando la relación on_delete=PROTECT existente entre TasaCambio y Moneda mediante un endpoint de activación/desactivación en lugar de eliminación física.

Pruebas automáticas: creación de 6 tests con APITestCase cubriendo listar, registrar, validación de código duplicado, editar, borrado lógico y reactivación de una moneda, confirmando que la suite completa del proyecto pasó de 36 a 42 tests, todos en estado OK.

## 2. Enlaces / Historial de Chats

Chat 1 (Setup del entorno, CRUD de Monedas, Jira y Git): https://chatgpt.com/c/6aa4164d-6ef4-83e9-8185-2b23325ded22
