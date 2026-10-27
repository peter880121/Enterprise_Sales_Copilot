import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
# Same Argon2 work for unknown users, never a usable credential.
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("password must have 12 to 128 characters")
    return hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def csrf_token(key: str, session_id: str, nonce: bytes) -> str:
    return hmac.new(key.encode(), session_id.encode() + nonce, hashlib.sha256).hexdigest()
