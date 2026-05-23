from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from app.config import settings

# connection pool — ป้องกัน connection leak และ handle concurrent requests
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=settings.database_url,
        )
    return _pool

@contextmanager
def get_conn():
    """Context manager — auto return connection to pool"""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

def init_db():
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         TEXT PRIMARY KEY,
                api_key    TEXT UNIQUE NOT NULL,
                name       TEXT,
                email      TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_notes (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content      TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMPTZ,
                error        TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_user ON raw_notes(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_status ON raw_notes(status)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content      TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT '',
                type         TEXT NOT NULL
                             CHECK (type IN ('task', 'idea', 'event', 'reference', 'personal')),
                scope        TEXT NOT NULL,
                importance   REAL NOT NULL CHECK (importance >= 0 AND importance <= 1),
                source_note  TEXT NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                embedding    vector(1536),
                read_count   INTEGER NOT NULL DEFAULT 0,
                last_read_at TIMESTAMPTZ,
                pinned       BOOLEAN NOT NULL DEFAULT FALSE,
                version      INTEGER NOT NULL DEFAULT 1
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_facts_user_id ON facts(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_facts_content_hash ON facts(user_id, content_hash)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_facts_scope ON facts(user_id, scope)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(user_id, importance DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_facts_pinned ON facts(user_id, pinned) WHERE pinned = TRUE")

        # migrate: เพิ่ม columns ที่อาจยังไม่มีใน DB เก่า
        for col, definition in [
            ("email",    "TEXT"),
            ("updated_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("pinned",   "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("version",  "INTEGER NOT NULL DEFAULT 1"),
            ("error",    "TEXT"),
        ]:
            cur.execute(f"""
                ALTER TABLE {'users' if col == 'email' else 'facts' if col in ('updated_at','pinned','version') else 'raw_notes'}
                ADD COLUMN IF NOT EXISTS {col} {definition}
            """)

        con.commit()
        cur.close()