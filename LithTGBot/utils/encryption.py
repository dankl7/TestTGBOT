import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from config import settings

ENCRYPTION_KEY = settings.encryption_key.encode()


def _derive_key(password: bytes) -> bytes:
    salt = b"max-bridge-salt-v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(password)


_KEY = _derive_key(ENCRYPTION_KEY)
_AESGCM = AESGCM(_KEY)


def encrypt_token(token: str) -> str:
    nonce = os.urandom(12)
    ct = _AESGCM.encrypt(nonce, token.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_token(encrypted: str) -> str:
    data = base64.b64decode(encrypted)
    nonce = data[:12]
    ct = data[12:]
    return _AESGCM.decrypt(nonce, ct, None).decode()