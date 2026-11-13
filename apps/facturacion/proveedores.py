"""Proveedores de facturación electrónica: a quién se le envía cada factura.

Hay dos, con la misma interfaz (``emitir`` y ``consultar``), y ``obtener_proveedor()``
elige uno según ``settings.FACTURACION_PROVEEDOR``:

* **Simulado** (por defecto): aprueba al instante y fabrica un CDC con la forma de uno
  real. Sirve para desarrollar, probar y mostrar el flujo sin credenciales; sus facturas
  no tienen validez tributaria. Con ``FACTURACION_SIMULADOR_DISPONIBLE=False`` responde
  como si estuviera caído, para mostrar el reintento.
* **Factura Segura** (``facturasegura``): la API REST de Factura Segura (ESI), que genera
  el documento electrónico, lo firma y lo manda a SIFEN. Sigue el contrato del
  documento "API de Factura Segura para ESI": una sola URL con ``POST``, el cuerpo
  ``{"operation": ..., "params": {...}}``, el token en el encabezado
  ``Authentication-Token`` y la respuesta ``{"code", "description", "results"}``, donde un
  ``code`` negativo es un error.

Todo error de comunicación o de rechazo del proveedor se traduce a ``ErrorFacturacion``:
quien llama decide qué hacer (reintentar), nunca se pierde la factura.
"""

import hashlib
from dataclasses import dataclass, field

import requests
from django.conf import settings

NOMBRE_SIMULADO = 'SIMULADO'
NOMBRE_FACTURA_SEGURA = 'FACTURA_SEGURA'

#: Segundos que se espera la respuesta de Factura Segura antes de darla por fallida.
TIEMPO_DE_ESPERA = 15


class ErrorFacturacion(Exception):
    """El proveedor no pudo atender el pedido. ``str(exc)`` explica el motivo."""


@dataclass
class RespuestaProveedor:
    """Lo que el proveedor contesta sobre un documento.

    ``estado_sifen`` es el estado en SIFEN tal como lo informa el proveedor (``Aprobado``,
    ``Rechazado``, ``SOL.APROBACION``...); ``datos`` es la respuesta completa, que se
    guarda en la factura como constancia.
    """

    cdc: str
    estado_sifen: str
    descripcion: str = ''
    datos: dict = field(default_factory=dict)


def _digito_verificador(digitos):
    """Dígito verificador del CDC: módulo 11 con pesos 2 a 11 de derecha a izquierda."""
    total, peso = 0, 2
    for digito in reversed(digitos):
        total += int(digito) * peso
        peso = 2 if peso == 11 else peso + 1
    resto = total % 11
    return str(11 - resto) if resto > 1 else '0'


class ProveedorSimulado:
    """Aprueba al instante, sin salir del proceso. No tiene validez tributaria."""

    nombre = NOMBRE_SIMULADO

    def _verificar_disponible(self):
        if not settings.FACTURACION_SIMULADOR_DISPONIBLE:
            raise ErrorFacturacion('El simulador de facturación no está disponible.')

    @staticmethod
    def _cdc(payload):
        """CDC de 44 dígitos con la estructura de SIFEN: tipo de documento, RUC y DV del
        emisor, establecimiento, punto, número, tipo de contribuyente, fecha, tipo de
        emisión, código de seguridad y dígito verificador."""
        fecha = payload['dFeEmiDE'][:10].replace('-', '')
        semilla = f"{payload['dNumDoc']}{payload['dFeEmiDE']}".encode()
        codigo_seguridad = str(int(hashlib.sha256(semilla).hexdigest(), 16) % 10**9).zfill(9)
        cuerpo = (
            f"{int(payload['iTiDE']):02d}{payload['dRucEm']:0>8}{payload['dDVEmi']}"
            f"{payload['dEst']}{payload['dPunExp']}{payload['dNumDoc']}"
            f"{payload['iTipCont']}{fecha}{payload['iTipEmi']}{codigo_seguridad}"
        )
        return cuerpo + _digito_verificador(cuerpo)

    def emitir(self, payload):
        self._verificar_disponible()
        cdc = self._cdc(payload)
        return RespuestaProveedor(
            cdc=cdc,
            estado_sifen='Aprobado',
            descripcion='0260 - Aprobado (simulado)',
            datos={'CDC': cdc, 'simulado': True},
        )

    def consultar(self, cdc):
        self._verificar_disponible()
        return RespuestaProveedor(
            cdc=cdc, estado_sifen='Aprobado', descripcion='0260 - Aprobado (simulado)',
            datos={'CDC': cdc, 'simulado': True},
        )


class ProveedorFacturaSegura:
    """Cliente de la API ``/misife00/v1/esi`` de Factura Segura."""

    nombre = NOMBRE_FACTURA_SEGURA

    def _llamar(self, operacion, params):
        """Hace una operación y devuelve su ``results``. Lanza ``ErrorFacturacion`` si no
        hay token, si no hay conexión, si responde con un HTTP o un JSON inesperado, o
        si el ``code`` es negativo."""
        if not settings.FACTURA_SEGURA_TOKEN:
            raise ErrorFacturacion('Falta configurar FACTURA_SEGURA_TOKEN.')
        try:
            respuesta = requests.post(
                settings.FACTURA_SEGURA_URL,
                json={'operation': operacion, 'params': params},
                headers={
                    'Authentication-Token': settings.FACTURA_SEGURA_TOKEN,
                    'accept': 'application/json',
                },
                timeout=TIEMPO_DE_ESPERA,
            )
        except requests.RequestException as exc:
            raise ErrorFacturacion('No se pudo conectar con Factura Segura.') from exc
        if respuesta.status_code != 200:
            raise ErrorFacturacion(f'Factura Segura respondió HTTP {respuesta.status_code}.')
        try:
            cuerpo = respuesta.json()
            codigo = int(cuerpo['code'])
        except (ValueError, KeyError, TypeError) as exc:
            raise ErrorFacturacion('Factura Segura devolvió una respuesta inválida.') from exc
        if codigo < 0:
            descripcion = cuerpo.get('description', '')
            raise ErrorFacturacion(f'Factura Segura rechazó "{operacion}": {descripcion}')
        return cuerpo.get('results') or []

    @staticmethod
    def _primero(resultados, clave, operacion):
        try:
            return resultados[0][clave]
        except (IndexError, KeyError, TypeError) as exc:
            raise ErrorFacturacion(
                f'Factura Segura devolvió una respuesta inesperada en "{operacion}".'
            ) from exc

    def emitir(self, payload):
        """``calcular_de`` completa los montos que calcula SIFEN, y ``generar_de``
        genera, firma y solicita la aprobación del documento. SIFEN lo aprueba después:
        hasta entonces el estado es ``SOL.APROBACION`` (ver ``consultar``)."""
        calculado = self._llamar('calcular_de', {'DE': payload})
        documento = self._primero(calculado, 'DE', 'calcular_de')
        generado = self._llamar('generar_de', {'DE': documento})
        cdc = self._primero(generado, 'CDC', 'generar_de')
        return RespuestaProveedor(
            cdc=cdc, estado_sifen='SOL.APROBACION',
            descripcion='Aprobación solicitada a SIFEN', datos={'CDC': cdc},
        )

    def consultar(self, cdc):
        """Estado del documento en SIFEN (``get_estado_sifen``). Factura Segura pide
        esperar un minuto después de ``generar_de`` para que sea significativo."""
        resultados = self._llamar('get_estado_sifen', {
            'CDC': cdc, 'dRucEm': settings.FACTURACION_EMISOR['ruc'],
        })
        if not resultados:
            raise ErrorFacturacion('Factura Segura no devolvió el estado del documento.')
        estado = resultados[0]
        return RespuestaProveedor(
            cdc=cdc,
            estado_sifen=estado.get('estado_sifen', ''),
            descripcion=estado.get('desc_sifen') or estado.get('error_sifen') or '',
            datos=estado,
        )


def obtener_proveedor():
    """El proveedor que indica ``settings.FACTURACION_PROVEEDOR``."""
    nombre = settings.FACTURACION_PROVEEDOR
    if nombre == 'simulado':
        return ProveedorSimulado()
    if nombre == 'facturasegura':
        return ProveedorFacturaSegura()
    raise ErrorFacturacion(f'Proveedor de facturación desconocido: "{nombre}".')
