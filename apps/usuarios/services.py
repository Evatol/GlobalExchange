import secrets
import string
from django.conf import settings
from keycloak import KeycloakAdmin


def generate_random_password(length=12):
    """Genera una contraseña aleatoria y segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_user_in_keycloak(username, email, first_name='', last_name='', role_name='cajero', temporary=True):
    """Crea un usuario en Keycloak y le asigna un rol asignado."""
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

    # 1. Crear el usuario en Keycloak
    user_id = keycloak_admin.create_user(user_payload)

    # 2. Asignar el rol al usuario (E4-102)
    role = keycloak_admin.get_realm_role(role_name)
    keycloak_admin.assign_realm_roles(user_id=user_id, roles=[role])

    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "role": role_name,
        "generated_password": auto_password
    }