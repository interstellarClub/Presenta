import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

INVITE_ALPHABET = string.ascii_uppercase + string.digits
INVITE_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def new_invite_code() -> str:
    raw = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalize_invite_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def invite_code_hash(code: str) -> str:
    message = normalize_invite_code(code).encode("utf-8")
    return hmac.new(
        settings.invite_hmac_salt.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True)
class ShareToken:
    raw: str
    digest: str


def new_share_slug() -> str:
    return secrets.token_urlsafe(12).replace("_", "").replace("-", "")[:16]


def new_share_token() -> ShareToken:
    raw = secrets.token_urlsafe(32)
    return ShareToken(raw=raw, digest=token_digest(raw))


def mask_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = settings.secret_key.encode("utf-8")
    return hmac.new(salt, ip.encode("utf-8"), hashlib.sha256).hexdigest()[:32]