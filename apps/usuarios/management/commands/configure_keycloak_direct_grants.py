"""Habilita "Direct Access Grants" en el cliente OIDC de Keycloak.

Necesario para que el usuario pueda cambiar su propia contraseña desde
"Mi Perfil" sin salir de la aplicación (RF9): para verificar la contraseña
actual, ``apps.usuarios.services.cambiar_password`` hace un login directo
(Resource Owner Password Credentials) contra Keycloak, que sólo funciona si
el cliente tiene este flag habilitado.

Es **idempotente**. No toca redirect URIs, el realm, ni usuarios.

Uso::

    python manage.py configure_keycloak_direct_grants
    python manage.py configure_keycloak_direct_grants --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError


class Command(BaseCommand):
    help = (
        'Habilita "Direct Access Grants Enabled" en el cliente OIDC de '
        "Keycloak (necesario para el cambio de contraseña propio desde Mi "
        "Perfil). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default=None)
        parser.add_argument("--admin-password", default=None)
        parser.add_argument(
            "--client-id",
            default=getattr(settings, "OIDC_RP_CLIENT_ID", "django-backend"),
            help="clientId del cliente OIDC (default: settings.OIDC_RP_CLIENT_ID).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        client_id = options["client_id"]

        admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=options["admin_user"] or settings.KEYCLOAK_ADMIN_USER,
            password=options["admin_password"] or settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=realm,
            user_realm_name="master",
            verify=True,
        )

        try:
            clients = admin.get_clients()
        except KeycloakError as exc:
            raise CommandError(f"No se pudo listar clientes en '{realm}':\n  {exc}") from exc

        client = next((c for c in clients if c.get("clientId") == client_id), None)
        if client is None:
            raise CommandError(f"No se encontró el cliente '{client_id}' en el realm '{realm}'.")

        actual = bool(client.get("directAccessGrantsEnabled"))
        self.stdout.write(self.style.MIGRATE_HEADING(f"Cliente '{client_id}' ({realm}):"))
        self.stdout.write(f"  directAccessGrantsEnabled actual: {actual}")

        if actual:
            self.stdout.write(self.style.SUCCESS("  Ya estaba habilitado. Nada que hacer."))
            return

        if options["dry_run"]:
            self.stdout.write("[dry-run] directAccessGrantsEnabled <- True")
            return

        try:
            admin.update_client(client["id"], {"directAccessGrantsEnabled": True})
        except KeycloakError as exc:
            raise CommandError(f"Falló el update del cliente:\n  {exc}") from exc

        refreshed = bool(admin.get_client(client["id"]).get("directAccessGrantsEnabled"))
        self.stdout.write(self.style.SUCCESS(f"  OK - directAccessGrantsEnabled: {refreshed}"))
