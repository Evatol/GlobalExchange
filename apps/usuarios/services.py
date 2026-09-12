import secrets
import string

from django.conf import settings
from django.core.mail import send_mail
from keycloak import KeycloakAdmin


def generate_random_password(length=12):
    """Genera una contraseña aleatoria y segura."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def enviar_credenciales_por_correo(email, username, password):
    """Envía al usuario su contraseña generada (RF3, alta por administrador).

    El backend de correo sale de ``settings.EMAIL_BACKEND`` (consola en
    desarrollo, SMTP en producción).
    """
    cuerpo = (
        f"Hola {username},\n\n"
        "Se creó tu cuenta en GlobalExchange.\n\n"
        f"Usuario: {username}\n"
        f"Contraseña temporal: {password}\n\n"
        "Al iniciar sesión por primera vez se te pedirá cambiarla.\n"
    )
    send_mail(
        subject="GlobalExchange - Credenciales de acceso",
        message=cuerpo,
        from_email=None,  # usa DEFAULT_FROM_EMAIL
        recipient_list=[email],
        fail_silently=False,
    )


# Roles de negocio del sistema (RF44 del ERS: administrador, analista,
# usuario final). Se crean en el realm con
# ``manage.py configure_keycloak_roles_negocio``.
ROLES_NEGOCIO = ("administrador", "analista", "usuario_final")


def _keycloak_admin():
    """Construye el cliente admin de Keycloak (mismo patrón en todo el módulo)."""
    return KeycloakAdmin(
        server_url=settings.KEYCLOAK_SERVER_URL,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_PASSWORD,
        realm_name=settings.KEYCLOAK_REALM,
        user_realm_name="master",
        verify=True,
    )


def listar_usuarios_con_roles():
    """Usuarios del realm con su rol de negocio actual (RF46/RF48), para la
    pantalla de gestión de roles. ``rol`` es ``None`` si todavía no tiene
    ninguno de los 3 roles de negocio asignado (ej. recién autoregistrado).
    """
    admin = _keycloak_admin()
    usuarios = []
    for u in admin.get_users(query={'max': 200}):
        roles_usuario = {r['name'] for r in admin.get_realm_roles_of_user(u['id'])}
        rol_actual = next((r for r in ROLES_NEGOCIO if r in roles_usuario), None)
        usuarios.append({
            'id': u['id'],
            'username': u.get('username', ''),
            'email': u.get('email', ''),
            'rol': rol_actual,
        })
    return sorted(usuarios, key=lambda u: u['username'])


def asignar_rol_negocio(username, rol):
    """Asigna ``rol`` (uno de ``ROLES_NEGOCIO``) al usuario ``username``.

    Un usuario tiene un solo rol de negocio a la vez: si ya tenía otro, se le
    quita antes de asignar el nuevo (RF46 desasignar + RF48 asignar, en un
    solo paso desde la pantalla de gestión de roles). Keycloak es la fuente
    de verdad; el cambio se refleja en Django recién en el próximo login de
    ese usuario (``CustomOIDCBackend._sync_roles``).
    """
    if rol not in ROLES_NEGOCIO:
        raise ValueError(f"Rol inválido: {rol!r}. Debe ser uno de {ROLES_NEGOCIO}.")

    admin = _keycloak_admin()
    user_id = admin.get_user_id(username)
    if not user_id:
        raise ValueError(f"No existe el usuario '{username}' en Keycloak.")

    roles_actuales = admin.get_realm_roles_of_user(user_id)
    a_quitar = [
        r for r in roles_actuales if r['name'] in ROLES_NEGOCIO and r['name'] != rol
    ]
    if a_quitar:
        admin.delete_realm_roles_of_user(user_id=user_id, roles=a_quitar)

    if not any(r['name'] == rol for r in roles_actuales):
        role = admin.get_realm_role(rol)
        admin.assign_realm_roles(user_id=user_id, roles=[role])

    return rol


def create_user_in_keycloak(username, email, first_name='', last_name='', role_name='cajero', temporary=True):
    """Crea un usuario en Keycloak y le asigna un rol asignado."""
    keycloak_admin = _keycloak_admin()

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