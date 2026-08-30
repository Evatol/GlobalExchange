from mozilla_django_oidc.auth import OIDCAuthenticationBackend


class CustomOIDCBackend(OIDCAuthenticationBackend):

    def create_user(self, claims):
        """Se ejecuta la primera vez que un usuario se registra/autentica vía Keycloak."""
        user = super().create_user(claims)
        return self._sync_user_profile(user, claims)

    def update_user(self, user, claims):
        """Se ejecuta cada vez que un usuario existente vuelve a iniciar sesión."""
        return self._sync_user_profile(user, claims)

    def _sync_user_profile(self, user, claims):
        """Mapea los claims recibidos de Keycloak con la base de datos de Django."""
        user.first_name = claims.get('given_name', '')
        user.last_name = claims.get('family_name', '')
        user.email = claims.get('email', '')

        # Mapear username si Keycloak lo provee
        preferred_username = claims.get('preferred_username')
        if preferred_username:
            user.username = preferred_username

        user.save()
        return user