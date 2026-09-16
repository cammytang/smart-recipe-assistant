"""Delete expired authentication sessions only; never print credentials."""
import sys
from pathlib import Path
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / 'src'))
from auth.config import AuthConfig
from database import open_pool


def main():
    load_dotenv(BACKEND / '.env')
    pool = None
    try:
        pool = open_pool(AuthConfig.from_env())
        with pool.connection() as connection:
            count = connection.execute('DELETE FROM user_sessions WHERE expires_at <= now()').rowcount
        print(f'Deleted {count} expired sessions.')
    except Exception:
        print('Session cleanup failed. Check database configuration and availability.', file=sys.stderr)
        return 1
    finally:
        if pool is not None:
            pool.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
