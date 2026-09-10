"""Agrega al cliente OIDC de Keycloak un mapper que expone los roles de realm
del usuario en un claim (por defecto ``roles``), para que Django los sincronice
en grupos y permisos (E4-120, criterio: los roles de Keycloak se reflejan en el
sistema).

Es **idempotente**: si el mapper ya existe (mismo claim), no hace nada.
No toca usuarios, realm ni SMTP.

Uso::

    python manage.py configure_keycloak_roles
    python manage.py configure_keycloak_roles --claim roles --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

MAPPER_NAME = "realm roles -> claim (django)"
DEFAULT_CLAIM = "roles"


class Command(BaseCommand):
    help = (
        "Agrega al cliente OIDC un protocol mapper de roles de realm -> claim, "
        "para que Django refleje los roles de Keycloak. Idempotente."
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
            "--claim",
            default=getattr(settings, "OIDC_ROLES_CLAIM", DEFAULT_CLAIM),
            help=f"nombre del claim (default: {DEFAULT_CLAIM}).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        client_id = options["client_id"]
        claim = options["claim"]

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

        mappers = admin.get_mappers_from_client(client["id"])
        existing = next(
            (
                m
                for m in mappers
                if m.get("protocolMapper") == "oidc-usermodel-realm-role-mapper"
                and (m.get("config") or {}).get("claim.name") == claim
            ),
            None,
        )

        self.stdout.write(self.style.MIGRATE_HEADING(f"Cliente '{client_id}' ({realm}):"))
        self.stdout.write(
            "  mappers de rol actuales: "
            + str([m.get("name") for m in mappers if "role" in m.get("protocolMapper", "")])
        )

        if existing:
            self.stdout.write(self.style.SUCCESS(
                f"  Ya existe un mapper de roles de realm hacia el claim '{claim}'. Nada que hacer."
            ))
            return

        payload = {
            "name": MAPPER_NAME,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-realm-role-mapper",
            "config": {
                "claim.name": claim,
                "jsonType.label": "String",
                "multivalued": "true",
                "usermodel.realmRoleMapping.rolePrefix": "",
                "userinfo.token.claim": "true",
                "id.token.claim": "true",
                "access.token.claim": "true",
            },
        }

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] add_mapper_to_client <- {payload}")
            return

        try:
            admin.add_mapper_to_client(client["id"], payload)
        except KeycloakError as exc:
            raise CommandError(f"Falló al agregar el mapper:\n  {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"  OK - mapper agregado. Los roles de realm van en el claim '{claim}' "
            "(userinfo + id token)."
        ))
        self.stdout.write(
            "  Los usuarios verán el cambio en su próximo inicio de sesión "
            "(CustomOIDCBackend._sync_roles)."
        )
