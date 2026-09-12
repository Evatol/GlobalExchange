"""Crea los roles de negocio del realm de Keycloak: administrador, analista
y usuario_final (RF44 del ERS; plan de permisos por rol para el próximo
sprint).

Es **idempotente**: si un rol ya existe, no lo toca. No asigna el rol a
ningún usuario ni modifica permisos de Django: para asignar un rol a un
usuario nuevo se usa ``manage.py crear_usuario_keycloak --rol <rol>``.

Uso::

    python manage.py configure_keycloak_roles_negocio
    python manage.py configure_keycloak_roles_negocio --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

# Roles de negocio y su descripción (quedan documentados en el propio realm).
ROLES_NEGOCIO = {
    "administrador": (
        "Acceso total: gestion de usuarios, clientes, monedas, cotizaciones "
        "y metodos de pago."
    ),
    "analista": (
        "Gestion de monedas y cotizaciones (ajuste manual de tasas, "
        "RF21/RF22 del ERS)."
    ),
    "usuario_final": (
        "Cliente del sistema: gestiona unicamente sus propios medios de "
        "pago (RF17)."
    ),
}


class Command(BaseCommand):
    help = (
        "Crea los roles de negocio del realm (administrador, analista, "
        "usuario_final). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default=None)
        parser.add_argument("--admin-password", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM

        admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=options["admin_user"] or settings.KEYCLOAK_ADMIN_USER,
            password=options["admin_password"] or settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=realm,
            user_realm_name="master",
            verify=True,
        )

        try:
            existentes = {r["name"] for r in admin.get_realm_roles()}
        except KeycloakError as exc:
            raise CommandError(
                f"No se pudo listar los roles del realm '{realm}':\n  {exc}"
            ) from exc

        self.stdout.write(self.style.MIGRATE_HEADING(f"Realm '{realm}':"))
        self.stdout.write(
            f"  roles de negocio ya presentes: "
            f"{sorted(existentes & ROLES_NEGOCIO.keys()) or '(ninguno)'}"
        )

        faltantes = [nombre for nombre in ROLES_NEGOCIO if nombre not in existentes]

        if not faltantes:
            self.stdout.write(
                self.style.SUCCESS("  Los 3 roles de negocio ya existen. Nada que hacer.")
            )
            return

        self.stdout.write(f"  a crear: {faltantes}")

        if options["dry_run"]:
            self.stdout.write("[dry-run] no se aplicó ningún cambio.")
            return

        for nombre in faltantes:
            try:
                admin.create_realm_role(
                    {"name": nombre, "description": ROLES_NEGOCIO[nombre]},
                    skip_exists=True,
                )
            except KeycloakError as exc:
                raise CommandError(
                    f"Falló al crear el rol '{nombre}':\n  {exc}"
                ) from exc

        actuales = {r["name"] for r in admin.get_realm_roles()}
        creados = sorted(actuales & ROLES_NEGOCIO.keys())
        self.stdout.write(
            self.style.SUCCESS(f"  OK - roles de negocio en el realm: {creados}")
        )
