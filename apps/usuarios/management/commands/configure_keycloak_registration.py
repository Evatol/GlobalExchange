"""Configura el realm de Keycloak para el autoregistro de usuarios con verificación
de correo (cambio de requerimiento que reincorpora el autoregistro tras el NCR_01).

El comando es **idempotente**: se puede correr varias veces y el realm queda siempre
en el mismo estado. Aplica, vía la API admin de Keycloak (``python-keycloak``):

    * ``registrationAllowed = true``          -> aparece el botón "Register".
    * ``verifyEmail = true``                   -> la cuenta nace pendiente de verificar.
    * ``registrationEmailAsUsername = false``  -> el username sigue siendo un campo aparte.
    * ``resetPasswordAllowed = true``          -> link "Olvidé mi contraseña" (E4-120).
    * ``bruteForceProtected = true``           -> bloqueo por intentos fallidos (E4-120).
    * ``smtpServer``                           -> SMTP real para verificación y recuperación.

Además **verifica en modo solo lectura** que el cliente OIDC tenga un redirect URI que
cubra la callback de Django.

NO crea usuarios, NO toca el flujo de login OIDC (``apps/usuarios/backends.py``), NO
toca el tema visual de Keycloak y NO reutiliza ``services.create_user_in_keycloak``
(eso es el alta por administrador, otro requerimiento).

Uso típico::

    python manage.py configure_keycloak_registration
    KEYCLOAK_SMTP_PASSWORD='xxxxxxxxxxxxxxxx' python manage.py configure_keycloak_registration
    python manage.py configure_keycloak_registration --dry-run
"""

import getpass
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

# Ruta de callback que expone mozilla-django-oidc, montada en /oidc/ por config/urls.py.
CALLBACK_PATH = "/oidc/callback/"
DEFAULT_CALLBACK_URI = "http://127.0.0.1:8000/oidc/callback/"

# Valores no secretos del SMTP (Gmail). Todos se pueden sobrescribir por opción.
SMTP_DEFAULT_HOST = "smtp.gmail.com"
SMTP_DEFAULT_PORT = "587"
SMTP_DEFAULT_FROM = "globalexchange314@gmail.com"
SMTP_DEFAULT_FROM_DISPLAY_NAME = "GlobalExchange"

# Campos del realm que mostramos como contexto (antes y después).
REALM_FLAG_KEYS = (
    "registrationAllowed",
    "verifyEmail",
    "registrationEmailAsUsername",
    "resetPasswordAllowed",
    "bruteForceProtected",
    "loginWithEmailAllowed",
    "duplicateEmailsAllowed",
)

# Lo que este comando garantiza en el realm. Keycloak queda a cargo de:
# autoregistro + verificación de correo + recuperación de contraseña +
# bloqueo por intentos fallidos (E4-120).
EXPECTED_FLAGS = {
    "registrationAllowed": True,
    "verifyEmail": True,
    "registrationEmailAsUsername": False,
    "resetPasswordAllowed": True,
    "bruteForceProtected": True,
}


class Command(BaseCommand):
    help = (
        "Deja en manos de Keycloak el autoregistro, la verificación de correo, la "
        "recuperación de contraseña y el bloqueo por intentos fallidos, y configura "
        "el SMTP del realm. Idempotente; no crea usuarios."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-user",
            default=None,
            help="Usuario admin de Keycloak (default: settings.KEYCLOAK_ADMIN_USER).",
        )
        parser.add_argument(
            "--admin-password",
            default=None,
            help="Password admin de Keycloak (default: settings.KEYCLOAK_ADMIN_PASSWORD).",
        )
        parser.add_argument("--smtp-host", default=SMTP_DEFAULT_HOST)
        parser.add_argument("--smtp-port", default=SMTP_DEFAULT_PORT)
        parser.add_argument("--smtp-from", default=SMTP_DEFAULT_FROM)
        parser.add_argument(
            "--smtp-from-display-name", default=SMTP_DEFAULT_FROM_DISPLAY_NAME
        )
        parser.add_argument(
            "--smtp-user",
            default=None,
            help="Usuario SMTP (default: el valor de --smtp-from).",
        )
        parser.add_argument(
            "--smtp-password",
            default=None,
            help=(
                "App Password de Gmail (16 caracteres; los espacios se ignoran). Si se "
                "omite se toma de la env var KEYCLOAK_SMTP_PASSWORD o se pide por consola."
            ),
        )
        parser.add_argument(
            "--skip-smtp",
            action="store_true",
            help="Solo aplica los flags de registro, sin tocar el SMTP del realm.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra el estado actual y lo que se cambiaría, sin escribir nada.",
        )

    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        dry_run = options["dry_run"]

        admin = self._connect(options)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Realm objetivo: {realm}  ({settings.KEYCLOAK_SERVER_URL})"
            )
        )

        try:
            current = admin.get_realm(realm)
        except KeycloakError as exc:
            raise CommandError(
                f"No se pudo leer el realm '{realm}'. ¿Keycloak está corriendo y las "
                f"credenciales admin son correctas?\n  {exc}"
            ) from exc

        self._print_state("Estado actual", current)

        # --- 1. Flags de autoregistro + verificación de correo ---------------- #
        registration_payload = {"realm": realm, **EXPECTED_FLAGS}
        if dry_run:
            self.stdout.write(f"[dry-run] PUT realm <- {registration_payload}")
        else:
            self._update_realm(
                admin, realm, registration_payload,
                "flags de autoregistro/verificación",
            )

        # --- 2. SMTP del realm ---------------------------------------------- #
        if options["skip_smtp"]:
            self.stdout.write(self.style.WARNING("SMTP: omitido (--skip-smtp)."))
        else:
            self._configure_smtp(admin, realm, options, dry_run)

        # --- 3. Releer y verificar ---------------------------------------- #
        if not dry_run:
            updated = admin.get_realm(realm)
            self._print_state("Estado nuevo", updated)
            self._assert_flags(updated)

        # --- 4. Verificación (solo lectura) del cliente OIDC ------------- #
        self._check_oidc_client(admin)

        self.stdout.write(
            self.style.SUCCESS(
                "Dry-run completado (sin cambios)." if dry_run else "Listo."
            )
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _connect(self, options):
        """Construye el cliente admin con el mismo patrón que apps/usuarios/services.py."""
        return KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=options["admin_user"] or settings.KEYCLOAK_ADMIN_USER,
            password=options["admin_password"] or settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=settings.KEYCLOAK_REALM,
            user_realm_name="master",
            verify=True,
        )

    def _update_realm(self, admin, realm, payload, label):
        try:
            admin.update_realm(realm, payload)
        except KeycloakError as exc:
            raise CommandError(f"Falló el update del realm ({label}):\n  {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"  OK - {label} aplicado"))

    def _configure_smtp(self, admin, realm, options, dry_run):
        smtp_user = options["smtp_user"] or options["smtp_from"]
        password = self._resolve_smtp_password(options, dry_run)

        smtp_server = {
            "host": options["smtp_host"],
            "port": str(options["smtp_port"]),
            "from": options["smtp_from"],
            "fromDisplayName": options["smtp_from_display_name"],
            "user": smtp_user,
            "auth": "true",
            "starttls": "true",  # Gmail 587 = STARTTLS
            "ssl": "false",
        }
        if password:
            smtp_server["password"] = password

        printable = dict(
            smtp_server, password=("***" if password else "(se mantiene el actual)")
        )
        if dry_run:
            self.stdout.write(f"[dry-run] PUT realm <- smtpServer={printable}")
            return

        self._update_realm(
            admin, realm, {"realm": realm, "smtpServer": smtp_server},
            "configuración SMTP",
        )
        self.stdout.write(f"  smtpServer aplicado: {printable}")

    def _resolve_smtp_password(self, options, dry_run):
        """Orden: --smtp-password  ->  env KEYCLOAK_SMTP_PASSWORD  ->  prompt interactivo."""
        raw = options["smtp_password"] or os.environ.get("KEYCLOAK_SMTP_PASSWORD")
        if raw:
            return self._normalize_app_password(raw)
        if dry_run:
            return None

        self.stdout.write(
            "Necesito el App Password de Gmail para el remitente "
            f"{options['smtp_from']} (no se guarda en ningún archivo)."
        )
        raw = getpass.getpass("Keycloak SMTP app password: ")
        pw = self._normalize_app_password(raw)
        if not pw:
            raise CommandError(
                "No se ingresó contraseña SMTP. Volvé a correr con --smtp-password, "
                "la env var KEYCLOAK_SMTP_PASSWORD, o --skip-smtp."
            )
        return pw

    @staticmethod
    def _normalize_app_password(value):
        # Gmail muestra el App Password en bloques ("abcd efgh ijkl mnop"); vale sin espacios.
        return value.strip().replace(" ", "")

    def _print_state(self, title, realm_repr):
        self.stdout.write(self.style.MIGRATE_HEADING(f"{title}:"))
        for key in REALM_FLAG_KEYS:
            self.stdout.write(f"  {key} = {realm_repr.get(key)}")
        smtp = realm_repr.get("smtpServer") or {}
        if smtp:
            shown = {
                k: smtp.get(k)
                for k in ("host", "port", "from", "fromDisplayName", "user",
                          "starttls", "ssl", "auth")
            }
            self.stdout.write(f"  smtpServer = {shown}")
            self.stdout.write(
                "  smtpServer.password = "
                + (
                    "(definido; Keycloak lo devuelve enmascarado)"
                    if smtp.get("password")
                    else "(vacío)"
                )
            )
        else:
            self.stdout.write("  smtpServer = (sin configurar)")

    def _assert_flags(self, realm_repr):
        wrong = {
            k: realm_repr.get(k)
            for k, expected in EXPECTED_FLAGS.items()
            if realm_repr.get(k) != expected
        }
        if wrong:
            raise CommandError(
                f"El realm no quedó con los valores esperados: {wrong} "
                f"(se esperaba {EXPECTED_FLAGS})."
            )
        self.stdout.write(self.style.SUCCESS("  OK - flags verificados en el realm"))

    def _check_oidc_client(self, admin):
        client_id = getattr(settings, "OIDC_RP_CLIENT_ID", "django-backend")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Cliente OIDC '{client_id}' (verificación solo lectura):"
            )
        )
        try:
            clients = admin.get_clients()
        except KeycloakError as exc:
            self.stdout.write(self.style.WARNING(f"  No se pudo listar clientes: {exc}"))
            return

        client = next((c for c in clients if c.get("clientId") == client_id), None)
        if client is None:
            self.stdout.write(
                self.style.WARNING(f"  No se encontró el cliente '{client_id}' en el realm.")
            )
            return

        redirect_uris = client.get("redirectUris") or []
        self.stdout.write(f"  redirectUris = {redirect_uris}")
        self.stdout.write(f"  webOrigins   = {client.get('webOrigins') or []}")
        if self._callback_covered(redirect_uris):
            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK - hay un redirect URI que cubre la callback de Django "
                    f"({CALLBACK_PATH})"
                )
            )
            origins = self._callback_origins(redirect_uris)
            if origins:
                self.stdout.write(
                    "  Entrá a Django por: "
                    + ", ".join(f"{o}/" for o in origins)
                    + "  (el host tiene que coincidir con el redirect URI)"
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  AVISO: ningún redirect URI parece cubrir {DEFAULT_CALLBACK_URI}. "
                    "Si el login normal ya funciona probablemente esté OK igual; "
                    "revisá el cliente en la consola de Keycloak."
                )
            )

    @staticmethod
    def _callback_covered(redirect_uris):
        for uri in redirect_uris:
            if CALLBACK_PATH in uri:
                return True
            if uri.endswith("/*") and DEFAULT_CALLBACK_URI.startswith(uri[:-1]):
                return True
        return False

    @staticmethod
    def _callback_origins(redirect_uris):
        """scheme://host[:port] de los redirect URIs que apuntan a la callback OIDC."""
        origins = []
        for uri in redirect_uris:
            if CALLBACK_PATH not in uri:
                continue
            parts = urlsplit(uri)
            origin = f"{parts.scheme}://{parts.netloc}"
            if origin not in origins:
                origins.append(origin)
        return origins
