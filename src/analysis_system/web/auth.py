"""Dang nhap cho dashboard: mot mat khau, bam bang scrypt, khong bao gio trong git.

The rule the API keys already follow, applied to the one other secret this
system has. `ASYS_PASSWORD_HASH` lives in `.env`, which is gitignored; the
plaintext password lives in whoever's head is running this and nowhere else.

Nothing here invents a default password. A dashboard that ships with one is a
dashboard with no password at all, and the first person to deploy it would
never know. With no hash configured the site refuses to start and says how to
make one.

scrypt from the standard library rather than a hashing package: it is the right
algorithm for this, it is already installed, and one password does not justify
a dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Final

# Where the hash is read from. The name says what it is, so nobody puts a
# plaintext password there by accident and wonders why it does not work.
PASSWORD_ENV: Final[str] = "ASYS_PASSWORD_HASH"
SESSION_ENV: Final[str] = "ASYS_SESSION_SECRET"

# scrypt parameters. n=2**14 costs about a tenth of a second, which nobody
# notices once per login and which makes guessing expensive.
SCRYPT_N: Final[int] = 2**14
SCRYPT_R: Final[int] = 8
SCRYPT_P: Final[int] = 1
SALT_BYTES: Final[int] = 16
# A colon rather than a dollar. `.env` is read by a shell, and a dollar sign in
# the middle of a value is a variable reference it expands to nothing.
SEPARATOR: Final[str] = ":"


class AuthError(RuntimeError):
    """The dashboard cannot be secured, so it will not start."""


@dataclass(frozen=True)
class Credential:
    """One stored password, as salt and hash."""

    salt: bytes
    digest: bytes

    def matches(self, password: str) -> bool:
        """True when this password produces the stored hash.

        Compared with `hmac.compare_digest` so the time taken says nothing
        about how much of the password was right.
        """
        return hmac.compare_digest(self.digest, _derive(password, self.salt))

    def encoded(self) -> str:
        """The form written into `.env`.

        Separated by a colon, not a dollar. `.env` is loaded with `. ./.env`,
        and a shell reading `abc$def` expands `$def` to nothing - so the hash
        arrived truncated and the dashboard refused a password that was right.
        Found by using it.
        """
        return f"{self.salt.hex()}{SEPARATOR}{self.digest.hex()}"


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)


def hash_password(password: str) -> Credential:
    """Turn a password into something safe to store.

    Raises:
        AuthError: the password is too short to be worth storing.
    """
    if len(password) < 12:
        raise AuthError(
            "Mat khau qua ngan - dat it nhat 12 ky tu. "
            "Day la mot dashboard mo ra toan bo du lieu phan tich."
        )
    # One salt, named once. Written the other way first - a fresh salt for the
    # stored field and another for the digest - and no password on earth would
    # have matched it.
    salt = secrets.token_bytes(SALT_BYTES)
    return Credential(salt=salt, digest=_derive(password, salt))


def stored_credential(environ: dict[str, str] | None = None) -> Credential:
    """The credential the environment configured.

    Raises:
        AuthError: nothing is configured, or what is there is not a hash. Both
            refuse rather than fall back: a dashboard that starts without a
            password is worse than one that will not start.
    """
    source = environ if environ is not None else dict(os.environ)
    raw = (source.get(PASSWORD_ENV) or "").strip()
    if not raw:
        raise AuthError(
            f"Chua dat {PASSWORD_ENV}. Tao mot cai bang:\n"
            "  asys set-password\n"
            f"roi dan dong ket qua vao .env (KHONG commit file do)."
        )
    salt, separator, digest = raw.partition(SEPARATOR)
    if not separator:
        raise AuthError(
            f"{PASSWORD_ENV} khong dung dinh dang. Phai la '<salt hex>:<hash hex>' - "
            "co ve ban da dat mat khau tho vao day. Chay 'asys set-password'."
        )
    try:
        return Credential(salt=bytes.fromhex(salt), digest=bytes.fromhex(digest))
    except ValueError as error:
        raise AuthError(f"{PASSWORD_ENV} khong doc duoc: {error}") from error


def session_secret(environ: dict[str, str] | None = None) -> str:
    """The key session cookies are signed with.

    Generated fresh when none is configured, which logs everybody out whenever
    the server restarts. That is the safe direction to fail in: the alternative
    is a fixed default, which would let anyone who has read this file forge a
    session on any deployment that never changed it.
    """
    source = environ if environ is not None else dict(os.environ)
    return (source.get(SESSION_ENV) or "").strip() or secrets.token_urlsafe(32)
