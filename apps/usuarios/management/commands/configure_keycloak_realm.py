"""Crea desde cero el realm y el cliente OIDC de Keycloak si todavía no
existen (bootstrap para un Keycloak recién levantado, ej. Docker Compose).

Un Keycloak nuevo sólo trae el realm "master": sin esto, un ``docker compose
up`` no tiene ni el realm "GlobalExchange" ni el cliente "django-backend"
que el resto de los comandos ``configure_keycloak_*`` esperan encontrar ya
creados.

Es **idempotente**: si el realm o el cliente ya existen, no los toca (no
pisa un realm de desarrollo ya configurado a mano). Pensado para encadenarse
con los demás comandos de configuración::

    python manage.py migrate
    python manage.py configure_keycloak_realm
    python manage.py configure_keycloak_roles_negocio
    python manage.py configure_keycloak_roles
    python manage.py configure_keycloak_locale

No configura SMTP ni autoregistro (``configure_keycloak_registration``):
eso requiere una contraseña de aplicación de Gmail real y se deja como
paso manual y opcional.

Uso::

    python manage.py configure_keycloak_realm
    python manage.py configure_keycloak_realm --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

DEFAULT_REDIRECT_URIS = [
    "http://localhost:8000/*",
    "http://127.0.0.1:8000/*",
]
DEFAULT_WEB_ORIGINS = ["+"]  # "+" = todos los orígenes de los redirect URIs
POST_LOGOUT_ATTR_KEY = "post.logout.redirect.uris"
DEFAULT_POST_LOGOUT_URIS = list(DEFAULT_REDIRECT_URIS)


class Command(BaseCommand):
    help = (
        "Crea el realm y el cliente OIDC de Keycloak si no existen "
        "(bootstrap para un Keycloak recién levantado). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default=None)
        parser.add_argument("--admin-password", default=None)
        parser.add_argument(
            "--client-id",
            default=getattr(settings, "OIDC_RP_CLIENT_ID", "django-backend"),
        )
        parser.add_argument(
            "--client-secret",
            default=getattr(settings, "OIDC_RP_CLIENT_SECRET", ""),
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        client_id = options["client_id"]
        client_secret = options["client_secret"]

        admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=options["admin_user"] or settings.KEYCLOAK_ADMIN_USER,
            password=options["admin_password"] or settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name="master",
            user_realm_name="master",
            verify=True,
        )

        try:
            realms_existentes = {r["realm"] for r in admin.get_realms()}
        except KeycloakError as exc:
            raise CommandError(f"No se pudo conectar a Keycloak:\n  {exc}") from exc

        self.stdout.write(self.style.MIGRATE_HEADING(f"Realm '{realm}':"))

        if realm not in realms_existentes:
            self.stdout.write(f"  no existe. Se va a crear.")
            if options["dry_run"]:
                self.stdout.write("[dry-run] create_realm(...)")
            else:
                try:
                    admin.create_realm(
                        {
                            "realm": realm,
                            "enabled": True,
                            "sslRequired": "none",
                            "registrationAllowed": False,
                            "loginWithEmailAllowed": True,
                        },
                        skip_exists=True,
                    )
                except KeycloakError as exc:
                    raise CommandError(f"Falló al crear el realm:\n  {exc}") from exc
                self.stdout.write(self.style.SUCCESS("  OK - realm creado."))
        else:
            self.stdout.write("  ya existe. No se toca.")

        if options["dry_run"] and realm not in realms_existentes:
            # En dry-run el realm no se creó de verdad: no hay a qué cambiar.
            self.stdout.write(self.style.WARNING(
                f"  Cliente '{client_id}': no se puede verificar en dry-run "
                "porque el realm todavía no existe."
            ))
            return

        admin.change_current_realm(realm)

        try:
            clientes = admin.get_clients()
        except KeycloakError as exc:
            raise CommandError(f"No se pudo listar clientes en '{realm}':\n  {exc}") from exc

        cliente = next((c for c in clientes if c.get("clientId") == client_id), None)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Cliente '{client_id}' ({realm}):"))

        if cliente is not None:
            self.stdout.write("  ya existe. No se toca.")
            return

        if not client_secret:
            raise CommandError(
                "No hay OIDC_RP_CLIENT_SECRET configurado (settings/--client-secret); "
                "hace falta para crear el cliente."
            )

        payload = {
            "clientId": client_id,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "secret": client_secret,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": False,
            "redirectUris": DEFAULT_REDIRECT_URIS,
            "webOrigins": DEFAULT_WEB_ORIGINS,
            "attributes": {
                POST_LOGOUT_ATTR_KEY: "##".join(DEFAULT_POST_LOGOUT_URIS),
            },
        }

        self.stdout.write(f"  no existe. Se va a crear con redirectUris: {DEFAULT_REDIRECT_URIS}")

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] create_client(...) <- {payload}")
            return

        try:
            admin.create_client(payload, skip_exists=True)
        except KeycloakError as exc:
            raise CommandError(f"Falló al crear el cliente:\n  {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            "  OK - cliente creado (standard flow + direct access grants habilitados)."
        ))
