from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, RateLimitError, APIError
from app.config import settings
from app.logger import log

client = OpenAI(api_key=settings.openai_api_key)

THINK_SYSTEM_PROMPT = """You are a personal cognitive assistant with access to the user's memory — a collection of atomic facts they have recorded over time.

Your job is NOT to search for keywords. Your job is to:
1. Read all the facts provided
2. Find patterns, connections, and insights
3. Answer the user's question as if you deeply understand their context
4. Be direct and specific — cite actual facts when relevant
5. If you see contradictions or evolution in thinking, point them out
6. Always respond in the same language as the user's question

You are the user's "second brain" — help them think, not just retrieve."""

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def synthesize(query: str, facts: list[dict], entities: list[dict]) -> dict:
    if not facts:
        return {
            "answer": "ยังไม่มีข้อมูลเพียงพอที่จะตอบคำถามนี้ครับ ลองจดบันทึกเพิ่มเติมก่อนได้เลย",
            "facts_used": 0,
            "entities_used": 0,
        }

    facts_text = "\n".join([
        f"[{i+1}] ({f['type']} | {f['scope']} | importance={f['importance']:.1f} | score={f['score']:.2f}) {f['content']}"
        for i, f in enumerate(facts)
    ])

    entities_text = ""
    if entities:
        entities_text = "\n\nKey entities and their frequency:\n" + "\n".join([
            f"- {e['name']} ({e.get('type', '?')}) — {e.get('fact_count', '?')} facts"
            for e in entities
        ])

    user_message = f"""User's question: {query}

Facts from memory ({len(facts)} facts, ranked by relevance):
{facts_text}{entities_text}

Synthesize an insightful answer. Be specific, cite facts by number when relevant."""

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": THINK_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=800,
        timeout=30,
    )

    log.info("synthesize_done", facts=len(facts), entities=len(entities))
    return {
        "answer": response.choices[0].message.content,
        "facts_used": len(facts),
        "entities_used": len(entities),
    }