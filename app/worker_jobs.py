import uuid
from datetime import datetime, timezone

from app.database import get_conn
from app.extractor import extract_facts, get_embedding
from app.consolidator import content_hash, is_duplicate
from app.graph import add_fact_to_graph
from app.logger import log

def get_existing_topics(user_id: str) -> dict[str, list[str]]:
    """
    ดึง scope พร้อม sample facts ของแต่ละ scope
    return: {"/work/q4": ["fact1", "fact2", "fact3"]}
    """
    with get_conn() as con:
        rows = con.execute("""
            SELECT scope, content
            FROM facts
            WHERE user_id = %s
            ORDER BY scope, importance DESC
        """, (user_id,)).fetchall()

    topics: dict[str, list[str]] = {}
    for scope, content in rows:
        if scope not in topics:
            topics[scope] = []
        if len(topics[scope]) < 3:  # เก็บแค่ 3 ตัวอย่างต่อ scope
            topics[scope].append(content)

    return topics

def process_ingest(note: str, user_id: str, raw_note_id: str):
    log.info("process_ingest_start", user_id=user_id, raw_note_id=raw_note_id)

    # ดึง existing topics พร้อม sample facts
    existing_topics = get_existing_topics(user_id)
    log.info("existing_topics", count=len(existing_topics))

    # extract พร้อม context ของ topics เดิม
    facts = extract_facts(note, existing_topics=existing_topics)
    saved, skipped = [], []
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as con:
        con.execute(
            "UPDATE raw_notes SET status = 'processing' WHERE id = %s",
            (raw_note_id,)
        )
        con.commit()

        for f in facts:
            embedding = get_embedding(f["content"])
            if is_duplicate(con, f["content"], embedding, user_id):
                skipped.append(f["content"])
                continue

            fact_id = str(uuid.uuid4())
            con.execute("""
                INSERT INTO facts
                  (id, user_id, content, content_hash, type, scope, importance,
                   source_note, created_at, updated_at, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
            """, (
                fact_id, user_id, f["content"], content_hash(f["content"]),
                f["type"], f["scope"], f["importance"],
                note, now, now, embedding,
            ))
            con.commit()

            try:
                add_fact_to_graph({
                    "id": fact_id, "content": f["content"],
                    "type": f["type"], "scope": f["scope"],
                    "importance": f["importance"],
                }, user_id)
            except Exception as e:
                log.warning("graph_add_failed", fact_id=fact_id, error=str(e))

            saved.append(fact_id)

        con.execute("""
            UPDATE raw_notes SET status = 'processed', processed_at = %s WHERE id = %s
        """, (now, raw_note_id))
        con.commit()

    log.info("process_ingest_done", saved=len(saved), skipped=len(skipped))
    return {"saved": len(saved), "skipped": len(skipped)}