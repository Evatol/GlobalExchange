import secrets
import string
from django.conf import settings
from keycloak import KeycloakAdmin

def generate_random_password(length=12):
    """Genera una contraseña aleatoria y segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def create_user_in_keycloak(username, email, first_name='', last_name='', temporary=True):
    """Crea un usuario en Keycloak de forma programática."""
    keycloak_admin = KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True
    )

    auto_password = generate_random_password()

    user_payload = {
        "email": email,
        "username": username,
        "firstName": first_name,
        "lastName": last_name,
        "enabled": True,
        "emailVerified": True,
        "credentials": [{
            "type": "password",
            "value": auto_password,
            "temporary": temporary
        }]
    }

    user_id = keycloak_admin.create_user(user_payload)

    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "generated_password": auto_password
    }