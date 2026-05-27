"""
topic_resolver.py — Episode → Scope resolver

Pipeline:
1. embed note ทั้งก้อน (episode embedding)
2. เทียบกับ scope_centroids ของ user
3. ถ้า similarity >= REUSE_THRESHOLD → reuse scope เดิม
4. ถ้าไม่มี scope ใกล้พอ → ให้ LLM สร้าง scope ใหม่จาก note
5. อัปเดต scope_centroid หลัง resolve
"""

import json
import numpy as np
from openai import OpenAI
from app.config import settings
from app.database import get_conn
from app.logger import log

client = OpenAI(api_key=settings.openai_api_key)

REUSE_THRESHOLD = 0.55   # similarity เกินนี้ → reuse scope เดิม
NEW_SCOPE_THRESHOLD = 0.35  # ต่ำกว่านี้ → สร้าง scope ใหม่แน่นอน
# ระหว่าง 0.35-0.55 → ให้ LLM ตัดสินใจโดย context

SCOPE_NAMING_PROMPT = """You are a topic classifier for a personal knowledge management system.

Given a note, assign a scope path in format: /category/topic
- category: work | personal | idea | learning | health | finance
- topic: specific subject (2-3 words max, lowercase, use hyphens)

Examples:
- Note about Q4 meeting → /work/q4-planning  
- Note about travel plans → /personal/travel
- Note about product feature idea → /idea/product
- Note about exercise → /personal/health

Return ONLY the scope path, nothing else."""

def get_scope_centroids(user_id: str) -> list[dict]:
    """ดึง scope centroids ทั้งหมดของ user"""
    with get_conn() as con:
        rows = con.execute("""
            SELECT scope, embedding, fact_count
            FROM scope_centroids
            WHERE user_id = %s AND embedding IS NOT NULL
        """, (user_id,)).fetchall()
    return [{"scope": r[0], "embedding": r[1], "fact_count": r[2]} for r in rows]

def cosine_similarity(a, b) -> float:
    """cosine similarity ระหว่าง 2 vectors"""
    a, b = np.array(a), np.array(b)
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def find_best_scope(note_embedding: list[float], centroids: list[dict]) -> tuple[str | None, float]:
    """หา scope ที่ใกล้เคียงที่สุด return (scope, similarity)"""
    if not centroids:
        return None, 0.0

    best_scope, best_sim = None, 0.0
    for c in centroids:
        if c["embedding"] is None:
            continue
        sim = cosine_similarity(note_embedding, c["embedding"])
        if sim > best_sim:
            best_sim = sim
            best_scope = c["scope"]

    return best_scope, best_sim

def generate_scope_name(note: str, existing_scopes: list[str]) -> str:
    """ให้ LLM สร้าง scope name จาก note"""
    existing_hint = ""
    if existing_scopes:
        existing_hint = f"\n\nExisting scopes (avoid duplicating these):\n" + "\n".join(f"- {s}" for s in existing_scopes)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SCOPE_NAMING_PROMPT},
            {"role": "user", "content": f"Note:\n{note}{existing_hint}"},
        ],
        max_tokens=20,
        timeout=10,
    )
    scope = response.choices[0].message.content.strip()
    # sanitize
    if not scope.startswith("/"):
        scope = "/" + scope
    return scope.lower().replace(" ", "-")

def update_scope_centroid(user_id: str, scope: str, new_embedding: list[float]):
    """
    อัปเดต centroid ของ scope โดย incremental average
    new_centroid = (old_centroid * n + new_embedding) / (n + 1)
    """
    with get_conn() as con:
        existing = con.execute("""
            SELECT embedding, fact_count
            FROM scope_centroids
            WHERE user_id = %s AND scope = %s
        """, (user_id, scope)).fetchone()

        if existing and existing[0] is not None:
            old_embedding = np.array(existing[0])
            n = existing[1]
            new_centroid = ((old_embedding * n) + np.array(new_embedding)) / (n + 1)
            con.execute("""
                UPDATE scope_centroids
                SET embedding = %s::vector, fact_count = fact_count + 1, updated_at = NOW()
                WHERE user_id = %s AND scope = %s
            """, (new_centroid.tolist(), user_id, scope))
        else:
            con.execute("""
                INSERT INTO scope_centroids (scope, user_id, embedding, fact_count)
                VALUES (%s, %s, %s::vector, 1)
                ON CONFLICT (scope, user_id) DO UPDATE
                SET embedding = %s::vector, fact_count = scope_centroids.fact_count + 1, updated_at = NOW()
            """, (scope, user_id, new_embedding, new_embedding))

        con.commit()

def resolve_scope(
    note: str,
    note_embedding: list[float],
    user_id: str,
) -> tuple[str, str]:
    """
    Resolve scope สำหรับ note ใหม่

    Returns: (scope, method)
    method: "reused" | "llm_decided" | "new"
    """
    centroids = get_scope_centroids(user_id)
    best_scope, best_sim = find_best_scope(note_embedding, centroids)

    log.info("scope_resolution",
             best_scope=best_scope,
             similarity=round(best_sim, 3),
             centroids_count=len(centroids))

    if best_sim >= REUSE_THRESHOLD:
        # ชัดเจนว่าเป็น scope เดิม
        log.info("scope_reused", scope=best_scope, similarity=best_sim)
        return best_scope, "reused"

    elif best_sim >= NEW_SCOPE_THRESHOLD and best_scope:
        # zone กลาง — ให้ LLM ตัดสินใจโดยดู content
        existing_scopes = [c["scope"] for c in centroids]
        with get_conn() as con:
            samples = con.execute("""
                SELECT content FROM facts
                WHERE user_id = %s AND scope = %s
                ORDER BY importance DESC LIMIT 3
            """, (user_id, best_scope)).fetchall()

        sample_text = " | ".join(r[0] for r in samples)
        decision_prompt = f"""Should this new note belong to existing scope "{best_scope}" or get a new scope?

Existing scope "{best_scope}" contains facts like: {sample_text}

New note: {note}

Reply with ONLY one of:
- "reuse" (if the new note is about the same topic)  
- "new" (if the new note is clearly a different topic)"""

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": decision_prompt}],
            max_tokens=5,
            timeout=10,
        )
        decision = response.choices[0].message.content.strip().lower()

        if "reuse" in decision:
            log.info("scope_llm_reused", scope=best_scope)
            return best_scope, "llm_decided"
        else:
            new_scope = generate_scope_name(note, existing_scopes)
            log.info("scope_llm_new", scope=new_scope)
            return new_scope, "llm_decided"

    else:
        # ห่างมาก → สร้างใหม่
        existing_scopes = [c["scope"] for c in centroids]
        new_scope = generate_scope_name(note, existing_scopes)
        log.info("scope_new", scope=new_scope)
        return new_scope, "new"