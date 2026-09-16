from psycopg.types.json import Jsonb
from .errors import AuthError
from .security import new_token, token_digest, valid_token

EMPTY_PROFILE = {
    'diet_preferences': [], 'allergies': [], 'disliked_ingredients': [],
    'favorite_ingredients': [], 'common_serving_size': None,
    'recent_dishes': [], 'rejected_patterns': [],
}


class AuthService:
    def __init__(self, pool, passwords, config):
        self.pool, self.passwords, self.config = pool, passwords, config

    def register(self, credentials):
        hashed = self.passwords.hash(credentials.password.get_secret_value())
        with self.pool.connection() as connection:
            user = connection.execute(
                'INSERT INTO users (username, password_hash) VALUES (%s, %s) '
                'ON CONFLICT (username) DO NOTHING RETURNING id, username, created_at',
                (credentials.username, hashed),
            ).fetchone()
            if user is None:
                raise AuthError(409, 'USERNAME_TAKEN', '用户名已被使用')
            connection.execute('INSERT INTO user_memories (user_id, profile) VALUES (%s, %s)',
                               (user['id'], Jsonb(EMPTY_PROFILE)))
        return user

    def login(self, credentials, old_token):
        with self.pool.connection() as connection:
            user = connection.execute('SELECT id, username, password_hash FROM users WHERE username = %s',
                                      (credentials.username,)).fetchone()
        verified = self.passwords.verify(user['password_hash'] if user else None,
                                         credentials.password.get_secret_value())
        if not verified or user is None:
            raise AuthError(401, 'INVALID_CREDENTIALS', '用户名或密码错误')
        token = new_token()
        with self.pool.connection() as connection:
            if valid_token(old_token):
                connection.execute('DELETE FROM user_sessions WHERE token_hash = %s', (token_digest(old_token),))
            session = connection.execute(
                "INSERT INTO user_sessions (token_hash, user_id, expires_at) "
                "VALUES (%s, %s, now() + %s * interval '1 second') RETURNING expires_at",
                (token_digest(token), user['id'], self.config.session_ttl),
            ).fetchone()
        return {'user': {'id': user['id'], 'username': user['username']}, **session}, token

    def current_user(self, token):
        if not valid_token(token):
            raise AuthError(401, 'UNAUTHENTICATED', '请先登录')
        with self.pool.connection() as connection:
            user = connection.execute(
                'SELECT u.id, u.username FROM user_sessions s JOIN users u ON u.id = s.user_id '
                'WHERE s.token_hash = %s AND s.expires_at > now()', (token_digest(token),),
            ).fetchone()
        if user is None:
            raise AuthError(401, 'UNAUTHENTICATED', '请先登录')
        return user

    def logout(self, token):
        if valid_token(token):
            with self.pool.connection() as connection:
                connection.execute('DELETE FROM user_sessions WHERE token_hash = %s', (token_digest(token),))

    def cleanup_expired(self):
        with self.pool.connection() as connection:
            count = connection.execute('DELETE FROM user_sessions WHERE expires_at <= now()').rowcount
        return count
