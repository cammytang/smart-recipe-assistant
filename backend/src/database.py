"""PostgreSQL pool lifecycle and read-only compatibility checks."""
from contextlib import asynccontextmanager
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool
from starlette.concurrency import run_in_threadpool


EXPECTED = {
    'users': {'id': 'uuid', 'username': 'character varying', 'password_hash': 'text', 'created_at': 'timestamp with time zone'},
    'user_sessions': {'token_hash': 'text', 'user_id': 'uuid', 'created_at': 'timestamp with time zone', 'expires_at': 'timestamp with time zone'},
    'user_memories': {'user_id': 'uuid', 'profile': 'jsonb', 'version': 'integer', 'updated_at': 'timestamp with time zone'},
}


def check_schema(pool):
    with pool.connection() as connection:
        rows = connection.execute(
            'SELECT table_name, column_name, data_type FROM information_schema.columns '
            'WHERE table_schema = current_schema() AND table_name = ANY(%s)',
            (list(EXPECTED),),
        ).fetchall()
        actual = {(r['table_name'], r['column_name']): r['data_type'] for r in rows}
        differences = [f'{table}.{column} must be {kind}' for table, columns in EXPECTED.items()
                       for column, kind in columns.items() if actual.get((table, column)) != kind]
        if differences:
            raise RuntimeError('Authentication schema mismatch: ' + '; '.join(differences))
        invalid = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM users WHERE username !~ '^[a-z0-9_]{3,64}$') AS invalid"
        ).fetchone()['invalid']
        if invalid:
            raise RuntimeError('Existing usernames require normalization review; no records were modified')


def open_pool(config):
    options = conninfo_to_dict(config.database_url).get('options', '')
    pool = ConnectionPool(
        config.database_url, open=False, min_size=config.pool_min, max_size=config.pool_max,
        timeout=5, max_waiting=32,
        kwargs={'row_factory': dict_row, 'connect_timeout': 5,
                'options': options + ' -c timezone=UTC -c statement_timeout=5000 -c lock_timeout=3000'},
        check=ConnectionPool.check_connection,
    )
    try:
        pool.open(wait=True, timeout=5)
        check_schema(pool)
        return pool
    except Exception:
        pool.close()
        raise


@asynccontextmanager
async def auth_lifespan(app):
    from auth.config import AuthConfig
    from auth.security import Passwords
    from auth.service import AuthService
    from auth.dependencies import RateLimiter

    config = getattr(app.state, 'auth_config', None) or AuthConfig.from_env()
    pool = await run_in_threadpool(open_pool, config)
    try:
        app.state.auth_config = config
        app.state.db_pool = pool
        app.state.auth_service = AuthService(pool, await run_in_threadpool(Passwords), config)
        app.state.auth_limiter = RateLimiter()
        yield
    finally:
        await run_in_threadpool(pool.close)
