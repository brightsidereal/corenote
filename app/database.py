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

        # users
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

        # raw_notes
        con.execute("""
            CREATE TABLE IF NOT EXISTS raw_notes (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content      TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending','processing','processed','failed')),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMPTZ,
                error        TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_user ON raw_notes(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_raw_notes_status ON raw_notes(status)")

        # episodes — note ทั้งก้อน 1 canvas session
        con.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id          TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                raw_note_id TEXT REFERENCES raw_notes(id),
                content     TEXT NOT NULL,           -- note ทั้งก้อน
                scope       TEXT NOT NULL,            -- scope ที่ resolve แล้ว
                embedding   vector(1536),             -- embed ของ note ทั้งก้อน
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_episodes_user ON episodes(user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_episodes_scope ON episodes(user_id, scope)")

        # scope_centroids — centroid embedding ของแต่ละ scope
        con.execute("""
            CREATE TABLE IF NOT EXISTS scope_centroids (
                scope       TEXT NOT NULL,
                user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                embedding   vector(1536),   -- average embedding ของทุก episode ใน scope นี้
                fact_count  INTEGER NOT NULL DEFAULT 0,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (scope, user_id)
            )
        """)

        # facts — atomic facts
        con.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id           TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                episode_id   TEXT REFERENCES episodes(id),   -- episode ที่ fact นี้มาจาก
                content      TEXT NOT NULL,
                content_hash TEXT NOT NULL DEFAULT '',
                type         TEXT NOT NULL
                             CHECK (type IN ('task','idea','event','reference','personal')),
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
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_pinned ON facts(user_id, pinned) WHERE pinned = TRUE")

        # migrate existing tables
        migrations = [
            ("users",    "email",      "TEXT"),
            ("facts",    "updated_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("facts",    "pinned",     "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("facts",    "version",    "INTEGER NOT NULL DEFAULT 1"),
            ("facts",    "episode_id", "TEXT"),
            ("raw_notes","error",      "TEXT"),
        ]
        for table, col, definition in migrations:
            con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {definition}")

        # index ที่ต้องสร้างหลัง migration
        con.execute("CREATE INDEX IF NOT EXISTS idx_facts_episode ON facts(episode_id)")

        con.commit()