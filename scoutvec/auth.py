# scoutvec/auth.py
"""Usuarios, contraseñas y sesiones.

Sin dependencias nuevas: el hashing usa hashlib.scrypt, que viene en la
biblioteca estandar y es un KDF con coste de memoria, no un hash rapido.
Nunca se guarda una contraseña, solo su derivacion; nunca se guarda un token
de sesion, solo su SHA-256, para que una copia de la base de datos no permita
suplantar sesiones vivas.
"""
import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

# parametros de scrypt: ~16 MB y ~100 ms por verificacion en esta maquina.
# Suben el coste de un ataque por diccionario en varios ordenes de magnitud
# frente a un hash rapido.
N, R, P, DKLEN, SALT = 2 ** 14, 8, 1, 32, 16

DIAS_SESION = 7
COOKIE = "scoutvec_session"


def hashear(password: str) -> str:
    """-> scrypt$n$r$p$salt$hash, todo en base64 urlsafe."""
    if not password:
        raise ValueError("contraseña vacia")
    salt = secrets.token_bytes(SALT)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=DKLEN)
    b64 = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    return f"scrypt${N}${R}${P}${b64(salt)}${b64(dk)}"


def verificar(password: str, guardado: str) -> bool:
    """Comparacion en tiempo constante; cualquier formato raro es un no."""
    try:
        alg, n, r, p, salt_b64, hash_b64 = guardado.split("$")
        if alg != "scrypt":
            return False
        unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        dk = hashlib.scrypt(password.encode(), salt=unb64(salt_b64),
                            n=int(n), r=int(r), p=int(p), dklen=DKLEN)
        return secrets.compare_digest(dk, unb64(hash_b64))
    except (ValueError, TypeError):
        return False


def politica(password: str) -> str | None:
    """Devuelve el motivo del rechazo, o None si la contraseña vale."""
    if len(password) < 10:
        return "la contraseña debe tener al menos 10 caracteres"
    if password.lower() in {"password", "contraseña", "scoutvec", "12345678910"}:
        return "esa contraseña es demasiado obvia"
    if password.strip() != password:
        return "la contraseña no puede empezar ni acabar con espacios"
    return None


# --------------------------------------------------------------- sesiones
def nuevo_token() -> tuple[str, str]:
    """(token para la cookie, sha256 para guardar). El token no se persiste."""
    t = secrets.token_urlsafe(32)
    return t, hashlib.sha256(t.encode()).hexdigest()


def huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def caduca_en() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=DIAS_SESION)


def cookie_segura(request=None) -> bool:
    """¿Marcar la cookie como Secure?

    Con "auto" (por defecto) se deduce del protocolo original, que detras de
    nginx viaja en X-Forwarded-Proto. Asi la misma configuracion sirve para
    https://scoutvec.enguillem.es y para http://localhost:8090; fijarlo a
    true a mano deja el login local inservible, porque el navegador no manda
    una cookie Secure por HTTP.
    """
    v = os.getenv("SESSION_COOKIE_SECURE", "auto").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    if request is None:
        return False
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto.split(",")[0].strip() == "https"


DDL = """
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  must_change   TINYINT(1) NOT NULL DEFAULT 0,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login    DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
  token_hash CHAR(64) PRIMARY KEY,
  user_id    INT NOT NULL,
  expires_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user (user_id),
  INDEX idx_exp  (expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
