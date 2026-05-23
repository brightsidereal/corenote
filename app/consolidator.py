import hashlib
from app.config import settings

def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().lower().encode()).hexdigest()

def is_duplicate(cur, content: str, embedding: list[float], user_id: str) -> bool:
    # Level 1: exact hash per user
    h = content_hash(content)
    cur.execute(
        "SELECT 1 FROM facts WHERE user_id = %s AND content_hash = %s LIMIT 1",
        (user_id, h)
    )
    if cur.fetchone():
        return True

    # Level 2: semantic similarity per user
    cur.execute("""
        SELECT 1 FROM facts
        WHERE user_id = %s
          AND 1 - (embedding <=> %s::vector) > %s
        LIMIT 1
    """, (user_id, embedding, settings.similarity_threshold))
    return cur.fetchone() is not None