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

SCOPE ASSIGNMENT RULES (follow strictly):
- If existing_topics are provided, compare the new fact's meaning against the example facts in each topic
- If the new fact is semantically similar to examples in an existing topic, USE that topic's scope
- Only create a NEW scope if the content is clearly unrelated to ALL existing topics
- When in doubt, prefer reusing an existing scope
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
def extract_facts(note: str, existing_topics: dict[str, list[str]] = None) -> list[dict]:
    """
    existing_topics: {scope: [sample fact contents]}
    เช่น {"/work/q4": ["ประชุม Q4 กับ Alex", "ต้องเตรียม deck"]}
    """
    log.info("extract_facts", note_length=len(note))

    topic_context = ""
    if existing_topics:
        lines = []
        for scope, samples in existing_topics.items():
            sample_text = " | ".join(samples[:3])  # เอาแค่ 3 ตัวอย่างต่อ scope
            lines.append(f"- {scope}: {sample_text}")
        topic_context = "\n\nexisting_topics (scope: example facts — reuse if semantically similar):\n" + "\n".join(lines)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Note:\n"""\n{note}\n"""{topic_context}'},
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