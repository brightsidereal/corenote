import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, RateLimitError, APIError
from app.config import settings
from app.logger import log

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are an atomic fact extractor for a personal knowledge management system.

The scope has already been determined. Your job is ONLY to extract atomic facts from the note.

Each fact must be:
- A single, self-contained piece of information
- Not redundant with other facts  
- Labeled with a type: task | idea | event | reference | personal
- Always in the same language as the input note
- Use the provided scope for ALL facts

For each fact estimate importance: 0.0-1.0

Return ONLY valid JSON, no markdown:
{
  "facts": [
    {
      "content": "string",
      "type": "task|idea|event|reference|personal",
      "importance": 0.0,
      "scope": "/scope/path"
    }
  ]
}"""

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def extract_facts(note: str, scope: str) -> list[dict]:
    """
    Extract atomic facts จาก note
    scope ถูก resolve มาแล้วจาก topic_resolver — ไม่ต้องให้ LLM เดาเอง
    """
    log.info("extract_facts", note_length=len(note), scope=scope)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Scope: {scope}\n\nNote:\n"""\n{note}\n"""'},
        ],
        response_format={"type": "json_object"},
        timeout=30,
    )
    facts = json.loads(response.choices[0].message.content)["facts"]

    # enforce scope — ป้องกัน LLM เปลี่ยน scope เอง
    for f in facts:
        f["scope"] = scope

    log.info("extract_facts_done", count=len(facts))
    return facts

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def get_embedding(text: str) -> list[float]:
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=text,
        timeout=10,
    )
    return response.data[0].embedding