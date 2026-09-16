"""Validated authentication settings. Never include secrets in errors."""
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AuthConfig:
    database_url: str = field(repr=False)
    allowed_origins: tuple[str, ...] = ('http://localhost:5173',)
    environment: str = 'development'
    cookie_secure: bool = False
    session_ttl: int = 604800
    pool_min: int = 1
    pool_max: int = 5

    def __post_init__(self):
        if not self.database_url.strip():
            raise ValueError('DATABASE_URL is required')
        if self.environment not in {'development', 'test', 'production'}:
            raise ValueError('APP_ENV must be development, test or production')
        if self.session_ttl < 1 or not 1 <= self.pool_min <= self.pool_max:
            raise ValueError('Invalid session TTL or database pool bounds')
        if not self.allowed_origins:
            raise ValueError('AUTH_ALLOWED_ORIGINS must not be empty')
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                    or parsed.path or parsed.query or parsed.fragment
                    or parsed.username or parsed.password or '*' in origin):
                raise ValueError('AUTH_ALLOWED_ORIGINS must contain exact HTTP(S) origins')
            try:
                parsed.port
            except ValueError:
                raise ValueError('Invalid origin port') from None
            if self.environment == 'production' and parsed.scheme != 'https':
                raise ValueError('Production origins must use HTTPS')
        if self.environment == 'production' and not self.cookie_secure:
            raise ValueError('Production requires AUTH_COOKIE_SECURE=true')

    @classmethod
    def from_env(cls):
        secure = os.getenv('AUTH_COOKIE_SECURE', 'false').lower()
        if secure not in {'true', 'false'}:
            raise ValueError('AUTH_COOKIE_SECURE must be true or false')
        return cls(
            database_url=os.getenv('DATABASE_URL', ''),
            allowed_origins=tuple(x.strip() for x in os.getenv(
                'AUTH_ALLOWED_ORIGINS', 'http://localhost:5173').split(',') if x.strip()),
            environment=os.getenv('APP_ENV', 'development'),
            cookie_secure=secure == 'true',
            session_ttl=int(os.getenv('AUTH_SESSION_TTL_SECONDS', '604800')),
            pool_min=int(os.getenv('DB_POOL_MIN_SIZE', '1')),
            pool_max=int(os.getenv('DB_POOL_MAX_SIZE', '5')),
        )
