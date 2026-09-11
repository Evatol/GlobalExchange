from django.conf import settings
from django.contrib.auth.models import Group
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

# Roles internos de Keycloak que no representan un rol de negocio y no deben
# convertirse en grupos de Django.
DEFAULT_IGNORED_ROLES = (
    "offline_access",
    "uma_authorization",
)

# Roles de Keycloak que otorgan acceso al panel de administración de Django.
DEFAULT_ADMIN_ROLES = ("admin", "administrador")


class CustomOIDCBackend(OIDCAuthenticationBackend):
    """Backend OIDC que, además de autenticar, sincroniza perfil, roles y estado
    del usuario desde Keycloak hacia la base de Django (E4-120 / RF8).

    Keycloak es la fuente de verdad: en cada inicio de sesión se recalculan los
    grupos y los permisos de acceso al admin a partir de los roles de realm que
    vienen en el token.
    """

    def create_user(self, claims):
        """Se ejecuta la primera vez que un usuario se registra/autentica vía Keycloak."""
        user = super().create_user(claims)
        return self._sync_user_profile(user, claims)

    def update_user(self, user, claims):
        """Se ejecuta cada vez que un usuario existente vuelve a iniciar sesión."""
        return self._sync_user_profile(user, claims)

    def _sync_user_profile(self, user, claims):
        """Mapea los claims recibidos de Keycloak con la base de datos de Django."""
        user.first_name = claims.get("given_name", "")
        user.last_name = claims.get("family_name", "")
        user.email = claims.get("email", "")

        # Mapear username si Keycloak lo provee
        preferred_username = claims.get("preferred_username")
        if preferred_username:
            user.username = preferred_username

        self._sync_roles(user, claims)

        user.save()
        self._sync_usuario_negocio(user)
        return user

    @staticmethod
    def _sync_usuario_negocio(user):
        """Mantiene un registro ``Usuario`` (modelo de negocio) espejando al
        ``User`` de auth, para poder asociarlo a clientes (RF42) y elegir el
        cliente activo (RF43).

        El puente es el ``username`` (ambos usan el ``preferred_username`` de
        Keycloak). Los datos complementarios (teléfono, dirección) los edita el
        propio usuario, así que sólo se sincronizan nombre y correo.
        """
        from .models import Usuario

        usuario, creado = Usuario.objects.get_or_create(
            username=user.username,
            defaults={
                "email": user.email or f"{user.username}@sin-correo.local",
                "nombres": user.first_name,
                "apellidos": user.last_name,
            },
        )
        if not creado:
            usuario.email = user.email or usuario.email
            usuario.nombres = user.first_name or usuario.nombres
            usuario.apellidos = user.last_name or usuario.apellidos
            usuario.save(update_fields=["email", "nombres", "apellidos"])

    def _sync_roles(self, user, claims):
        """Refleja los roles de realm de Keycloak en grupos de Django y en los
        flags de acceso al admin.

        Requiere un mapper en el cliente OIDC que exponga los roles de realm en
        un claim (por defecto ``roles``); lo configura
        ``manage.py configure_keycloak_roles``. Si el claim no viene, no se toca
        nada, para no romper el login si el mapper todavía no está.
        """
        claim_name = getattr(settings, "OIDC_ROLES_CLAIM", "roles")
        raw_roles = claims.get(claim_name)
        if raw_roles is None:
            return

        ignored = set(getattr(settings, "OIDC_IGNORED_ROLES", DEFAULT_IGNORED_ROLES))
        roles = {
            role
            for role in raw_roles
            if role not in ignored and not role.startswith("default-roles-")
        }

        groups = []
        for name in sorted(roles):
            group, _ = Group.objects.get_or_create(name=name)
            groups.append(group)
        user.save()  # asegura PK antes de tocar la relación M2M
        user.groups.set(groups)

        admin_roles = set(getattr(settings, "OIDC_ADMIN_ROLES", DEFAULT_ADMIN_ROLES))
        is_admin = bool(roles & admin_roles)
        user.is_staff = is_admin
        user.is_superuser = is_admin
