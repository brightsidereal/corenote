import hashlib
from app.config import settings

def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().lower().encode()).hexdigest()

def is_duplicate(con, content: str, embedding: list[float], user_id: str) -> bool:
    h = content_hash(content)
    row = con.execute(
        "SELECT 1 FROM facts WHERE user_id = %s AND content_hash = %s LIMIT 1",
        (user_id, h)
    ).fetchone()
    if row:
        return True

    row = con.execute("""
        SELECT 1 FROM facts
        WHERE user_id = %s
          AND 1 - (embedding <=> %s::vector) > %s
        LIMIT 1
    """, (user_id, embedding, settings.similarity_threshold)).fetchone()
    return row is not None