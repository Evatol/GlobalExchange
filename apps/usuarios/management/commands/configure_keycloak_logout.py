"""Configura en Keycloak el/los ``post logout redirect URI`` del cliente OIDC.

Necesario para el cierre de sesión RP-initiated: cuando Django redirige a Keycloak
para cerrar la sesión SSO, Keycloak sólo acepta volver a una URL que esté en la
lista de "Valid post logout redirect URIs" del cliente.

Es **idempotente**. No toca redirect URIs de login, ni el realm, ni usuarios.

Uso::

    python manage.py configure_keycloak_logout
    python manage.py configure_keycloak_logout --uri 'http://127.0.0.1:8000/*' --uri 'http://localhost:8000/*'
    python manage.py configure_keycloak_logout --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

# Clave del atributo del cliente en Keycloak; múltiples valores van separados por "##".
ATTR_KEY = "post.logout.redirect.uris"
DEFAULT_URIS = ["http://127.0.0.1:8000/*"]


class Command(BaseCommand):
    help = (
        "Agrega los post-logout redirect URIs al cliente OIDC en Keycloak "
        "(para el logout RP-initiated). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default=None)
        parser.add_argument("--admin-password", default=None)
        parser.add_argument(
            "--client-id",
            default=getattr(settings, "OIDC_RP_CLIENT_ID", "django-backend"),
            help="clientId del cliente OIDC (default: settings.OIDC_RP_CLIENT_ID).",
        )
        parser.add_argument(
            "--uri",
            action="append",
            dest="uris",
            default=None,
            help=f"post-logout redirect URI (repetible). Default: {DEFAULT_URIS}",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        client_id = options["client_id"]
        wanted = options["uris"] or list(DEFAULT_URIS)

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

        attributes = dict(client.get("attributes") or {})
        current = [u for u in (attributes.get(ATTR_KEY) or "").split("##") if u]
        merged = list(dict.fromkeys(current + wanted))  # unión preservando orden

        self.stdout.write(self.style.MIGRATE_HEADING(f"Cliente '{client_id}' ({realm}):"))
        self.stdout.write(f"  post-logout actuales: {current or '(ninguno)'}")
        self.stdout.write(f"  deseados:             {wanted}")

        if set(merged) == set(current):
            self.stdout.write(self.style.SUCCESS("  Ya estaban configurados. Nada que hacer."))
            return

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {ATTR_KEY} <- {merged}")
            return

        attributes[ATTR_KEY] = "##".join(merged)
        try:
            admin.update_client(client["id"], {"attributes": attributes})
        except KeycloakError as exc:
            raise CommandError(f"Falló el update del cliente:\n  {exc}") from exc

        refreshed = admin.get_client(client["id"]).get("attributes", {}).get(ATTR_KEY, "")
        self.stdout.write(self.style.SUCCESS(f"  OK - post-logout redirect URIs: {refreshed.split('##')}"))
