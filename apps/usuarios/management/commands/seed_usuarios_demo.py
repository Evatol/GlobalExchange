"""Crea (si no existen) 3 usuarios de demostración, uno por cada rol de
negocio, con contraseña fija -- pensado para que cualquiera del equipo
pueda levantar el sistema (ej. con Docker Compose) y probar los 3 roles
sin tener que andar generando ni compartiendo contraseñas.

Es **idempotente**: si un usuario ya existe, no le toca la contraseña (para
no pisar una que alguien ya cambió); solo se asegura de que tenga asignado
el rol de negocio correspondiente.

Uso::

    python manage.py seed_usuarios_demo
    python manage.py seed_usuarios_demo --password OtraClave1! --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak.exceptions import KeycloakError

from apps.usuarios import services

DEFAULT_PASSWORD = "Demo1234!"

# username -> (nombre, apellido, rol de negocio)
USUARIOS_DEMO = {
    "admin_demo": ("Admin", "Demo", "administrador"),
    "analista_demo": ("Analista", "Demo", "analista"),
    "cliente_demo": ("Cliente", "Demo", "usuario_final"),
}


class Command(BaseCommand):
    help = (
        "Crea admin_demo/analista_demo/cliente_demo (uno por rol de "
        "negocio) con contraseña fija, para pruebas en equipo. Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        password = options["password"]
        admin = services._keycloak_admin()

        for username, (nombre, apellido, rol) in USUARIOS_DEMO.items():
            self.stdout.write(self.style.MIGRATE_HEADING(f"'{username}' ({rol}):"))

            try:
                user_id = admin.get_user_id(username)
            except KeycloakError as exc:
                raise CommandError(f"No se pudo consultar '{username}':\n  {exc}") from exc

            if user_id is None:
                self.stdout.write(f"  no existe. Se va a crear con contraseña fija.")
                if options["dry_run"]:
                    self.stdout.write("[dry-run] create_user(...) + set_user_password(...)")
                else:
                    email = f"{username}@example.com"
                    try:
                        user_id = admin.create_user({
                            "username": username,
                            "email": email,
                            "firstName": nombre,
                            "lastName": apellido,
                            "enabled": True,
                            "emailVerified": True,
                            "credentials": [{
                                "type": "password",
                                "value": password,
                                "temporary": False,
                            }],
                        })
                    except KeycloakError as exc:
                        raise CommandError(f"Falló al crear '{username}':\n  {exc}") from exc
                    self.stdout.write(self.style.SUCCESS(
                        f"  OK - creado (contraseña: {password})."
                    ))
            else:
                self.stdout.write("  ya existe. No se toca la contraseña.")

            if options["dry_run"]:
                self.stdout.write(f"[dry-run] asignar_rol_negocio('{username}', '{rol}')")
                continue

            try:
                services.asignar_rol_negocio(username, rol)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS(f"  OK - rol '{rol}' asegurado."))

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"\nListo. Los 3 usan la contraseña '{password}' "
                "(admin_demo / analista_demo / cliente_demo)."
            ))
