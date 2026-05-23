import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from app.database import get_conn
from app.extractor import get_embedding
from app.scoring import composite_score
from app.auth import get_current_user
from app.queue import ingest_queue
from app.worker_jobs import process_ingest
from app.graph import query_by_entity, query_related_facts, get_entity_graph, get_top_entities
from app.mode_detector import detect_mode
from app.thinker import synthesize
from app.errors import NotFoundError
from app.logger import log

router = APIRouter(dependencies=[Depends(get_current_user)])

class IngestRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=10000)

class RecallRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    scope: str = Field(default=None)
    mode: str = Field(default="auto")

class ThinkRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=20)
    scope: str = Field(default=None)
    mode: str = Field(default="auto")

def _recall_facts(query: str, user_id: str, top_k: int, scope: str, mode: str):
    explicit = None if mode == "auto" else mode
    detected_mode, reason = detect_mode(query, explicit)
    embedding = get_embedding(query)

    with get_conn() as con:
        scope_filter = "AND scope LIKE %s" if scope else ""
        params = [embedding, user_id, embedding]
        if scope:
            params.insert(2, f"{scope}%")

        rows = con.execute(f"""
            SELECT id, content, type, scope, importance, created_at,
                   read_count, last_read_at, pinned,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM facts
            WHERE user_id = %s {scope_filter}
            ORDER BY embedding <=> %s::vector
            LIMIT 50
        """, params).fetchall()

        cols = ["id","content","type","scope","importance","created_at",
                "read_count","last_read_at","pinned","similarity"]
        scored = []
        for r in rows:
            d = dict(zip(cols, r))
            d["score"] = composite_score(d["similarity"], d["importance"], d["created_at"], detected_mode)
            scored.append(d)

        scored.sort(key=lambda x: -x["score"])
        top = scored[:top_k]

        now = datetime.now(timezone.utc).isoformat()
        ids = [r["id"] for r in top]
        if ids:
            con.execute("""
                UPDATE facts SET read_count = read_count + 1, last_read_at = %s
                WHERE id = ANY(%s) AND user_id = %s
            """, (now, ids, user_id))
            con.commit()

    return top, detected_mode, reason

@router.post("/ingest")
def ingest(req: IngestRequest, user: dict = Depends(get_current_user)):
    with get_conn() as con:
        raw_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO raw_notes (id, user_id, content) VALUES (%s, %s, %s)",
            (raw_id, user["id"], req.note)
        )
        con.commit()

    job = ingest_queue.enqueue(process_ingest, req.note, user["id"], raw_id, job_timeout=120)
    log.info("ingest_queued", user_id=user["id"], raw_note_id=raw_id, job_id=job.id)
    return {"status": "queued", "raw_note_id": raw_id, "job_id": job.id,
            "message": "รับ note แล้ว กำลังประมวลผลใน background"}

@router.get("/ingest/{raw_note_id}/status")
def ingest_status(raw_note_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as con:
        row = con.execute("""
            SELECT id, status, created_at, processed_at, error
            FROM raw_notes WHERE id = %s AND user_id = %s
        """, (raw_note_id, user["id"])).fetchone()

    if not row:
        raise NotFoundError("raw_note")
    return dict(zip(["id","status","created_at","processed_at","error"], row))

@router.post("/recall")
def recall(req: RecallRequest, user: dict = Depends(get_current_user)):
    top, mode, reason = _recall_facts(req.query, user["id"], req.top_k, req.scope, req.mode)
    return {"mode": mode, "mode_reason": reason, "results": top}

@router.post("/think")
def think(req: ThinkRequest, user: dict = Depends(get_current_user)):
    top, mode, reason = _recall_facts(req.query, user["id"], req.top_k, req.scope, req.mode)
    entities = get_top_entities(user["id"], limit=10)
    result = synthesize(req.query, top, entities)
    log.info("think", user_id=user["id"], facts_used=result["facts_used"])
    return {"mode": mode, "mode_reason": reason, "answer": result["answer"],
            "facts_used": result["facts_used"], "entities_used": result["entities_used"], "facts": top}

@router.get("/facts")
def list_facts(scope: str = Query(default=None), user: dict = Depends(get_current_user)):
    with get_conn() as con:
        if scope:
            rows = con.execute("""
                SELECT id, content, type, scope, importance, created_at,
                       read_count, last_read_at, pinned
                FROM facts WHERE user_id = %s AND scope LIKE %s ORDER BY importance DESC
            """, (user["id"], f"{scope}%")).fetchall()
        else:
            rows = con.execute("""
                SELECT id, content, type, scope, importance, created_at,
                       read_count, last_read_at, pinned
                FROM facts WHERE user_id = %s ORDER BY importance DESC
            """, (user["id"],)).fetchall()
    cols = ["id","content","type","scope","importance","created_at","read_count","last_read_at","pinned"]
    facts = [dict(zip(cols, r)) for r in rows]
    return {"facts": facts, "count": len(facts)}

@router.patch("/facts/{fact_id}/pin")
def pin_fact(fact_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as con:
        row = con.execute("""
            UPDATE facts SET pinned = NOT pinned
            WHERE id = %s AND user_id = %s RETURNING id, pinned
        """, (fact_id, user["id"])).fetchone()
        con.commit()
    if not row:
        raise NotFoundError("fact")
    return {"id": row[0], "pinned": row[1]}

@router.get("/scopes")
def list_scopes(user: dict = Depends(get_current_user)):
    with get_conn() as con:
        rows = con.execute("""
            SELECT scope, COUNT(*) as count,
                   ROUND(AVG(importance)::numeric, 2) as avg_importance,
                   MAX(last_read_at) as last_accessed
            FROM facts WHERE user_id = %s GROUP BY scope ORDER BY count DESC
        """, (user["id"],)).fetchall()
    cols = ["scope","count","avg_importance","last_accessed"]
    return {"scopes": [dict(zip(cols, r)) for r in rows]}

@router.post("/forget")
def forget_cold_facts(dry_run: bool = Query(default=True), user: dict = Depends(get_current_user)):
    with get_conn() as con:
        rows = con.execute("""
            SELECT id, content, scope, importance, read_count, last_read_at
            FROM facts
            WHERE user_id = %s AND importance < 0.2 AND read_count = 0
              AND pinned = FALSE AND created_at < NOW() - INTERVAL '180 days'
        """, (user["id"],)).fetchall()
        cols = ["id","content","scope","importance","read_count","last_read_at"]
        candidates = [dict(zip(cols, r)) for r in rows]
        if not dry_run and candidates:
            ids = [r["id"] for r in candidates]
            con.execute("DELETE FROM facts WHERE id = ANY(%s) AND user_id = %s", (ids, user["id"]))
            con.commit()
    log.info("forget", user_id=user["id"], candidates=len(candidates), dry_run=dry_run)
    return {"dry_run": dry_run, "candidates": len(candidates), "facts": candidates}

@router.get("/graph")
def graph_overview(user: dict = Depends(get_current_user)):
    return get_entity_graph(user["id"])

@router.get("/graph/entity/{entity_name}")
def graph_entity(entity_name: str, user: dict = Depends(get_current_user)):
    return {"results": query_by_entity(entity_name, user["id"])}

@router.get("/graph/related/{fact_id}")
def graph_related(fact_id: str, user: dict = Depends(get_current_user)):
    return {"results": query_related_facts(fact_id, user["id"])}