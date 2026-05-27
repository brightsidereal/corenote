import uuid
from datetime import datetime, timezone

from app.database import get_conn
from app.extractor import extract_facts, get_embedding
from app.consolidator import content_hash, is_duplicate
from app.graph import add_fact_to_graph
from app.topic_resolver import resolve_scope, update_scope_centroid
from app.logger import log

def process_ingest(note: str, user_id: str, raw_note_id: str):
    log.info("process_ingest_start", user_id=user_id, raw_note_id=raw_note_id)
    now = datetime.now(timezone.utc).isoformat()

    # ── Step 1: Embed note ทั้งก้อน (episode embedding)
    note_embedding = get_embedding(note)

    # ── Step 2: Resolve scope ด้วย centroid similarity
    scope, method = resolve_scope(note, note_embedding, user_id)
    log.info("scope_resolved", scope=scope, method=method)

    # ── Step 3: Save episode
    episode_id = str(uuid.uuid4())
    with get_conn() as con:
        con.execute("""
            INSERT INTO episodes (id, user_id, raw_note_id, content, scope, embedding, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
        """, (episode_id, user_id, raw_note_id, note, scope, note_embedding, now))
        con.execute(
            "UPDATE raw_notes SET status = 'processing' WHERE id = %s",
            (raw_note_id,)
        )
        con.commit()

    # ── Step 4: Extract atomic facts (scope รู้แล้ว)
    facts = extract_facts(note, scope=scope)
    saved, skipped = [], []

    # ── Step 5: Save facts
    with get_conn() as con:
        for f in facts:
            embedding = get_embedding(f["content"])
            if is_duplicate(con, f["content"], embedding, user_id):
                skipped.append(f["content"])
                continue

            fact_id = str(uuid.uuid4())
            con.execute("""
                INSERT INTO facts
                  (id, user_id, episode_id, content, content_hash, type, scope,
                   importance, source_note, created_at, updated_at, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            """, (
                fact_id, user_id, episode_id,
                f["content"], content_hash(f["content"]),
                f["type"], scope, f["importance"],
                note, now, now, embedding,
            ))
            con.commit()

            # graph best-effort
            try:
                add_fact_to_graph({
                    "id": fact_id, "content": f["content"],
                    "type": f["type"], "scope": scope,
                    "importance": f["importance"],
                }, user_id)
            except Exception as e:
                log.warning("graph_add_failed", fact_id=fact_id, error=str(e))

            saved.append(fact_id)

        con.execute("""
            UPDATE raw_notes SET status = 'processed', processed_at = %s WHERE id = %s
        """, (now, raw_note_id))
        con.commit()

    # ── Step 6: Update scope centroid (incremental average)
    if saved:
        update_scope_centroid(user_id, scope, note_embedding)

    log.info("process_ingest_done", saved=len(saved), skipped=len(skipped), scope=scope)
    return {"saved": len(saved), "skipped": len(skipped), "scope": scope}