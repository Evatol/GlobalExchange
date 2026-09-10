"""Alta de usuario por el administrador (RF1-RF3).

El admin indica usuario + correo; el sistema:

  1. crea el usuario en Keycloak (API admin),
  2. le genera una contraseña aleatoria segura (``secrets``),
  3. le asigna un rol de realm,
  4. le envía la contraseña por correo.

La contraseña es ``temporary``: Keycloak obliga a cambiarla en el primer login.

Uso::

    python manage.py crear_usuario_keycloak jperez jperez@example.com --rol cajero
    python manage.py crear_usuario_keycloak jperez jperez@example.com \\
        --nombre Juan --apellido Perez --rol analista
    python manage.py crear_usuario_keycloak demo demo@example.com --no-email --mostrar-password
"""

from django.core.management.base import BaseCommand, CommandError

from keycloak.exceptions import KeycloakError

from apps.usuarios import services


class Command(BaseCommand):
    help = (
        "Alta de usuario por el administrador: lo crea en Keycloak con contrasena "
        "aleatoria, le asigna un rol y le envia la contrasena por correo (RF1-RF3)."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("email")
        parser.add_argument("--nombre", default="", help="First name en Keycloak.")
        parser.add_argument("--apellido", default="", help="Last name en Keycloak.")
        parser.add_argument(
            "--rol", default="cajero", help="Rol de realm a asignar (default: cajero)."
        )
        parser.add_argument(
            "--no-email",
            action="store_true",
            help="No enviar el correo (para pruebas).",
        )
        parser.add_argument(
            "--mostrar-password",
            action="store_true",
            help="Imprime la contrasena generada en pantalla (por defecto no se muestra).",
        )

    def handle(self, *args, **options):
        username = options["username"]
        email = options["email"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Alta de '{username}' <{email}> con rol '{options['rol']}'"
            )
        )

        try:
            resultado = services.create_user_in_keycloak(
                username=username,
                email=email,
                first_name=options["nombre"],
                last_name=options["apellido"],
                role_name=options["rol"],
                temporary=True,
            )
        except KeycloakError as exc:
            raise CommandError(
                f"Keycloak rechazo el alta (¿usuario/correo ya existe? ¿rol '{options['rol']}' "
                f"no existe? ¿credenciales admin?):\n  {exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"  OK - creado en Keycloak (id {resultado['user_id']}), rol '{resultado['role']}' asignado"
        ))

        password = resultado["generated_password"]
        if options["mostrar_password"]:
            self.stdout.write(f"  Contrasena generada: {password}")

        if options["no_email"]:
            self.stdout.write(self.style.WARNING("  Correo: omitido (--no-email)."))
            return

        try:
            services.enviar_credenciales_por_correo(email, username, password)
        except Exception as exc:  # noqa: BLE001 - reportamos cualquier fallo de envio
            raise CommandError(
                "El usuario se creo en Keycloak pero fallo el envio del correo:\n"
                f"  {exc}\n"
                "Revisa EMAIL_BACKEND / EMAIL_HOST_PASSWORD, o reenvia la clave a mano."
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"  OK - contrasena enviada a {email}"))
