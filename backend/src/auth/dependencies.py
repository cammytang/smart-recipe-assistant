import math
import time
from threading import Lock
from fastapi import Request
from .errors import AuthError
from .security import COOKIE_NAME


class RateLimiter:
    """Bounded, thread-safe fixed windows for a single worker only."""
    def __init__(self, clock=time.monotonic, capacity=10000):
        self.clock, self.capacity = clock, capacity
        self.entries = {}
        self.lock = Lock()

    def hit(self, key, limit, window):
        with self.lock:
            now = self.clock()
            self.entries = {k: v for k, v in self.entries.items() if v[1] > now}
            if key not in self.entries and len(self.entries) >= self.capacity:
                raise AuthError(429, 'RATE_LIMITED', '请求过于频繁，请稍后重试', {'Retry-After': '60'})
            count, end = self.entries.get(key, (0, now + window))
            if count >= limit:
                raise AuthError(429, 'RATE_LIMITED', '请求过于频繁，请稍后重试',
                                {'Retry-After': str(max(1, math.ceil(end - now)))})
            self.entries[key] = count + 1, end


def check_origin(request):
    if request.method not in {'POST', 'DELETE'}:
        return
    origins = request.headers.getlist('origin')
    if len(origins) != 1 or origins[0] not in request.app.state.auth_config.allowed_origins:
        raise AuthError(403, 'ORIGIN_NOT_ALLOWED', '请求来源不允许')


def check_write_request(request):
    check_origin(request)
    if request.method == 'POST':
        address = request.client.host if request.client else 'unknown'
        registration = request.url.path.rstrip('/') == '/api/v1/users'
        request.app.state.auth_limiter.hit(
            ('register' if registration else 'login', address),
            5 if registration else 20, 600 if registration else 60,
        )
        if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
            raise AuthError(415, 'UNSUPPORTED_MEDIA_TYPE', '请使用 application/json')


def get_current_user(request: Request):
    return request.app.state.auth_service.current_user(request.cookies.get(COOKIE_NAME))
