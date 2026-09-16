"""User-scoped PostgreSQL memory, with atomic read/merge/write transactions."""
from copy import deepcopy
from uuid import UUID
from psycopg.types.json import Jsonb
from auth.service import EMPTY_PROFILE


class MemoryRepository:
    def __init__(self, pool, user_id):
        self.pool = pool
        self.user_id = UUID(str(user_id))

    def _ensure(self, connection):
        connection.execute(
            'INSERT INTO user_memories (user_id, profile) VALUES (%s, %s) '
            'ON CONFLICT (user_id) DO NOTHING', (self.user_id, Jsonb(EMPTY_PROFILE)),
        )

    @staticmethod
    def _view(row):
        return {**row['profile'], 'version': row['version'], 'updated_at': row['updated_at'].isoformat()}

    def load(self):
        with self.pool.connection() as connection:
            row = connection.execute(
                'SELECT profile, version, updated_at FROM user_memories WHERE user_id = %s',
                (self.user_id,),
            ).fetchone()
            if row is None:
                self._ensure(connection)
                row = connection.execute(
                    'SELECT profile, version, updated_at FROM user_memories WHERE user_id = %s',
                    (self.user_id,),
                ).fetchone()
        return self._view(row)

    def update(self, transform):
        with self.pool.connection() as connection:
            self._ensure(connection)
            row = connection.execute(
                'SELECT profile FROM user_memories WHERE user_id = %s FOR UPDATE',
                (self.user_id,),
            ).fetchone()
            profile = transform(deepcopy(row['profile']))
            profile.pop('version', None)
            profile.pop('updated_at', None)
            result = connection.execute(
                'UPDATE user_memories SET profile = %s, version = version + 1, updated_at = now() '
                'WHERE user_id = %s RETURNING profile, version, updated_at',
                (Jsonb(profile), self.user_id),
            ).fetchone()
        return self._view(result)
