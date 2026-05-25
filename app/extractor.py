import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import OpenAI, RateLimitError, APIError
from app.config import settings
from app.logger import log

client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """You are an atomic fact extractor for a personal knowledge management system.

Read the entire note first, identify context groups (bullets that continue the same topic share scope).
Then extract atomic facts.

Each fact must be:
- A single, self-contained piece of information
- Not redundant with other facts
- Labeled with a type: task | idea | event | reference | personal
- Always in the same language as the input note

For each fact also estimate:
- importance: 0.0-1.0
- scope: short path like /work/q4 or /idea/product or /personal/health

IMPORTANT — scope assignment rules:
- If existing_scopes are provided, prefer reusing an existing scope when the content is related
- Only create a new scope if the content is clearly different from all existing scopes
- Use the most specific existing scope that matches
- Format: /category/topic (e.g. /work/q4, /personal/health, /idea/product)

Return ONLY valid JSON, no markdown, no explanation:
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
def extract_facts(note: str, existing_scopes: list[str] = None) -> list[dict]:
    log.info("extract_facts", note_length=len(note))

    scope_context = ""
    if existing_scopes:
        scope_context = f"\n\nexisting_scopes (prefer reusing these if content is related):\n" + \
                       "\n".join(f"- {s}" for s in existing_scopes)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Note:\n"""\n{note}\n"""{scope_context}'},
        ],
        response_format={"type": "json_object"},
        timeout=30,
    )
    facts = json.loads(response.choices[0].message.content)["facts"]
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