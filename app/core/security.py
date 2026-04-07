import base64
import hashlib
import hmac
import os
from typing import Final


SCRYPT_N: Final[int] = 2**14
SCRYPT_R: Final[int] = 8
SCRYPT_P: Final[int] = 1
SCRYPT_LENGTH: Final[int] = 64


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LENGTH,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = password_hash.split("$", 5)
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False

    computed = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.urlsafe_b64decode(salt_b64.encode("ascii")),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=SCRYPT_LENGTH,
    )
    expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
    return hmac.compare_digest(computed, expected)

