# Documentación de Asistencia de IA (CHIA) - Tarea E4-192: Administrar terminales

**Fecha:** Octubre de 2026
**Proyecto:** Global Exchange - Sistema Casa de Cambios (IS2)
**Rama:** `feature/E4-192-administrar-terminales`
**Link:** https://share.gemini.google/qC4PUCrf5rtO

---

## 1. Resumen de la Interacción y Consultas
Durante el desarrollo de la tarea **E4-192**, se consultó al asistente de IA para alinear la implementación técnica con:
1. Las directrices de la guía del proyecto de Ingeniería de Software 2.
2. El feedback recibido en el Sprint 4 (enfocado en plataformas simuladas, carga manual de efectivo por parte del administrador y separación de cajas de cajeros tradicionales).
3. La correcta resolución de dependencias atómicas y validaciones en el backend de Django.

---

## 2. Decisiones de Diseño y Arquitectura Adoptadas con la IA

* **Modelo de Terminal y Estado Operativo:**
  Se acordó modelar la `Terminal` separando sus estados operativos (`ACTIVA`, `INACTIVA`, `MANTENIMIENTO`) de las cajas de los cajeros. Esto permite realizar bajas lógicas sin alterar los saldos ni romper los historiales financieros existentes.

* **Creación Atómica y Stock Inicial:**
  Siguiendo el feedback de que el efectivo no debe depender de integraciones externas de pago ni de hardware físico en esta etapa simulada, se estructuró un alta mediante transacciones atómicas (`transaction.atomic`) en `services.py`. Al crear la terminal, se genera automáticamente su caja vinculada y el inventario inicial de billetes por denominación cargado manualmente por el administrador.

* **Bloqueo Estricto en el Backend:**
  Se implementaron validaciones obligatorias en el servidor. Si una terminal se encuentra en estado `INACTIVA` o `MANTENIMIENTO`, cualquier intento de iniciar una operación (ya sea desde la API o la pantalla de simulación) es bloqueado de inmediato con un mensaje explicativo claro.

---

## 3. Pruebas y Validación Realizada
* Se diseñaron y ejecutaron pruebas unitarias específicas en `test_terminales.py`.
* Se validó el funcionamiento integral pasando exitosamente las **156 pruebas del módulo caja**.
* Se aplicó la migración aditiva local `0006_terminal` para alinear el esquema de base de datos.
* Se compiló y verificó la documentación técnica en Sphinx (`caja.rst`) sin errores.