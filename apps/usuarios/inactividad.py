"""apps/usuarios/inactividad.py - cierre de sesión por inactividad (E4-195).

Inyecta, en cada página HTML que ve un usuario autenticado, un script que:

1. cuenta el tiempo sin actividad (mouse, teclado, toque, scroll), compartido
   entre pestañas mediante localStorage;
2. muestra un aviso con cuenta regresiva ``INACTIVIDAD_AVISO_SEGUNDOS`` antes
   de cumplirse el límite ``INACTIVIDAD_SEGUNDOS``;
3. al cumplirse el límite, envía el mismo POST a ``oidc_logout`` que el botón
   "Cerrar Sesión" del menú, que cierra la sesión de Django y la de Keycloak.

Como respaldo del lado servidor, settings.py hace vencer también la sesión de
Django (SESSION_COOKIE_AGE) y la renueva con cada request.
"""
import json

from django.conf import settings
from django.middleware.csrf import get_token
from django.urls import reverse

_SCRIPT = r"""
<script>
(function () {
  var cfg = __CONFIG__;
  var CLAVE = 'ge_ultima_actividad';
  var limite = cfg.limite * 1000;
  var aviso = Math.min(cfg.aviso, cfg.limite) * 1000;
  var ultimo = Date.now();
  var ultimoRegistro = 0;
  var overlay = null;
  var cuenta = null;
  var cerrando = false;

  function compartida() {
    try { return parseInt(localStorage.getItem(CLAVE), 10) || 0; } catch (e) { return 0; }
  }

  function registrar() {
    ultimo = Date.now();
    try { localStorage.setItem(CLAVE, String(ultimo)); } catch (e) {}
  }

  function actividad() {
    // Con el aviso abierto solo cuenta el botón "Seguir conectado".
    if (overlay || cerrando) { return; }
    var t = Date.now();
    if (t - ultimoRegistro > 1000) { ultimoRegistro = t; registrar(); }
  }

  function seguir() {
    ocultarAviso();
    registrar();
    // Renueva la sesión de Django en el servidor.
    try { fetch(window.location.pathname, { method: 'HEAD', credentials: 'same-origin' }); } catch (e) {}
  }

  function mostrarAviso(segundos) {
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.setAttribute('role', 'alertdialog');
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.55);' +
        'z-index:2147483647;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;';
      var caja = document.createElement('div');
      caja.style.cssText = 'background:#fff;color:#212529;border-radius:8px;padding:24px;max-width:420px;' +
        'width:90%;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.3);';
      var titulo = document.createElement('h5');
      titulo.style.cssText = 'margin:0 0 12px;';
      titulo.textContent = 'Tu sesión está por cerrarse';
      var texto = document.createElement('p');
      texto.style.cssText = 'margin:0 0 16px;';
      texto.appendChild(document.createTextNode('Por inactividad, la sesión se cerrará en '));
      cuenta = document.createElement('strong');
      texto.appendChild(cuenta);
      texto.appendChild(document.createTextNode(' segundos.'));
      var boton = document.createElement('button');
      boton.type = 'button';
      boton.textContent = 'Seguir conectado';
      boton.style.cssText = 'background:#0d6efd;color:#fff;border:0;border-radius:6px;padding:8px 18px;cursor:pointer;';
      boton.addEventListener('click', seguir);
      caja.appendChild(titulo);
      caja.appendChild(texto);
      caja.appendChild(boton);
      overlay.appendChild(caja);
      document.body.appendChild(overlay);
      boton.focus();
    }
    cuenta.textContent = String(segundos);
  }

  function ocultarAviso() {
    if (overlay) {
      overlay.parentNode.removeChild(overlay);
      overlay = null;
      cuenta = null;
    }
  }

  function cerrarSesion() {
    cerrando = true;
    var f = document.createElement('form');
    f.method = 'post';
    f.action = cfg.logoutUrl;
    f.style.display = 'none';
    var token = document.createElement('input');
    token.type = 'hidden';
    token.name = 'csrfmiddlewaretoken';
    token.value = cfg.csrf;
    f.appendChild(token);
    document.body.appendChild(f);
    f.submit();
  }

  function tick() {
    if (cerrando) { return; }
    var inactivo = Date.now() - Math.max(ultimo, compartida());
    var restante = limite - inactivo;
    if (restante <= 0) { cerrarSesion(); }
    else if (restante <= aviso) { mostrarAviso(Math.ceil(restante / 1000)); }
    else { ocultarAviso(); }
  }

  ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'].forEach(function (nombre) {
    window.addEventListener(nombre, actividad, { passive: true, capture: true });
  });
  document.addEventListener('visibilitychange', tick);
  registrar();
  setInterval(tick, 1000);
})();
</script>
"""


class InactividadMiddleware:
    """Agrega el script de inactividad a las páginas HTML de usuarios
    autenticados. Va al final de MIDDLEWARE para que, al volver la respuesta,
    el CSRF de Django ya haya fijado su cookie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        user = getattr(request, 'user', None)
        if (
            user is None
            or not user.is_authenticated
            or response.streaming
            or response.status_code != 200
            or not response.get('Content-Type', '').startswith('text/html')
        ):
            return response

        html = response.content.decode(response.charset)
        pos = html.lower().rfind('</body>')
        if pos == -1:
            return response

        response.content = html[:pos] + self._script(request) + html[pos:]
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response

    @staticmethod
    def _script(request):
        limite = int(getattr(settings, 'INACTIVIDAD_SEGUNDOS', 300))
        aviso = int(getattr(settings, 'INACTIVIDAD_AVISO_SEGUNDOS', 30))
        config = json.dumps({
            'limite': limite,
            'aviso': min(aviso, limite),
            'logoutUrl': reverse('oidc_logout'),
            'csrf': get_token(request),
        }).replace('<', '\\u003c')
        return _SCRIPT.replace('__CONFIG__', config)