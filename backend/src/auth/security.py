import hashlib
import re
import secrets
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError

COOKIE_NAME = 'recipe_session'


class Passwords:
    def __init__(self):
        self.hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, type=Type.ID)
        self.dummy = self.hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password):
        return self.hasher.hash(password)

    def verify(self, encoded, password):
        try:
            return self.hasher.verify(encoded or self.dummy, password)
        except (VerificationError, InvalidHashError):
            return False


def new_token():
    return secrets.token_urlsafe(32)


def token_digest(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def valid_token(token):
    return isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token) is not None
