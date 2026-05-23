from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.config import settings

_pool: ConnectionPool = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=2,
            max_size=10,
            open=True,
        )
    return _pool

@contextmanager
def get_conn():
    with get_pool().connection() as conn:
        yield conn

def init_db():
    with get_conn() as con:
        con.execute("CREATE EXTENSION IF NOT EXISTS vector")

        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         TEXT PRIMARY KEY,
                api_key    TEXT UNIQUE NOT NULL,
                name       TEXT,
                email      TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        con.execute("""
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
        con.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_user ON raw_notes(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_status ON raw_notes(status)")

        con.execute("""
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
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_user_id ON facts(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_content_hash ON facts(user_id, content_hash)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_scope ON facts(user_id, scope)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(user_id, importance DESC)")

        # migrate existing tables
        for table, col, definition in [
            ("users", "email", "TEXT"),
            ("facts", "updated_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("facts", "pinned", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("facts", "version", "INTEGER NOT NULL DEFAULT 1"),
            ("raw_notes", "error", "TEXT"),
        ]:
            con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {definition}")

        con.commit()