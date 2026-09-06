"""Pone el realm de Keycloak en español: pantallas de login/registro/actualizar
contraseña y los correos que envía Keycloak (verificación de email, etc.).

Keycloak 26 ya trae las traducciones al español (login y email); alcanza con
habilitar i18n y fijar el locale por defecto. No hace falta tema custom.

Es **idempotente**. No toca usuarios, flows ni SMTP.

Uso::

    python manage.py configure_keycloak_locale
    python manage.py configure_keycloak_locale --also-english   # deja selector es/en
    python manage.py configure_keycloak_locale --dry-run
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from keycloak import KeycloakAdmin
from keycloak.exceptions import KeycloakError

DEFAULT_LOCALE = "es"


class Command(BaseCommand):
    help = "Configura el realm de Keycloak en español (UI + emails). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--admin-user", default=None)
        parser.add_argument("--admin-password", default=None)
        parser.add_argument("--locale", default=DEFAULT_LOCALE, help="locale por defecto (default: es).")
        parser.add_argument(
            "--also-english",
            action="store_true",
            help="dejar también 'en' como soportado (aparece un selector de idioma).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        realm = settings.KEYCLOAK_REALM
        locale = options["locale"]
        supported = [locale] + (["en"] if options["also_english"] and locale != "en" else [])

        admin = KeycloakAdmin(
            server_url=settings.KEYCLOAK_SERVER_URL,
            username=options["admin_user"] or settings.KEYCLOAK_ADMIN_USER,
            password=options["admin_password"] or settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name=realm,
            user_realm_name="master",
            verify=True,
        )

        try:
            current = admin.get_realm(realm)
        except KeycloakError as exc:
            raise CommandError(f"No se pudo leer el realm '{realm}':\n  {exc}") from exc

        self.stdout.write(self.style.MIGRATE_HEADING(f"Realm '{realm}' - estado actual:"))
        for k in ("internationalizationEnabled", "defaultLocale", "supportedLocales"):
            self.stdout.write(f"  {k} = {current.get(k)}")

        payload = {
            "realm": realm,
            "internationalizationEnabled": True,
            "defaultLocale": locale,
            "supportedLocales": supported,
        }

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] PUT realm <- {payload}")
            return

        try:
            admin.update_realm(realm, payload)
        except KeycloakError as exc:
            raise CommandError(f"Falló el update del realm:\n  {exc}") from exc

        updated = admin.get_realm(realm)
        self.stdout.write(self.style.MIGRATE_HEADING("Estado nuevo:"))
        for k in ("internationalizationEnabled", "defaultLocale", "supportedLocales"):
            self.stdout.write(f"  {k} = {updated.get(k)}")

        ok = (
            updated.get("internationalizationEnabled") is True
            and updated.get("defaultLocale") == locale
            and locale in (updated.get("supportedLocales") or [])
        )
        if not ok:
            raise CommandError("El realm no quedó con el locale esperado.")
        self.stdout.write(self.style.SUCCESS(
            "  OK - Keycloak en español (login, registro, actualizar contraseña y emails)."
        ))
        self.stdout.write(
            "  Nota: los usuarios ya existentes sin atributo 'locale' también reciben "
            "los emails en el idioma por defecto del realm."
        )
