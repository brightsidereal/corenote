import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
from openai import OpenAI, RateLimitError, APIError
from app.config import settings
from app.logger import log

driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password)
)
client = OpenAI(api_key=settings.openai_api_key)

ENTITY_EXTRACT_PROMPT = """Extract named entities from this fact.
Return ONLY valid JSON, no markdown:
{{
  "entities": [
    {{
      "name": "string",
      "type": "Person|Project|Topic|Place|Organization"
    }}
  ]
}}

Fact: "{fact}"
"""

@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
def extract_entities(fact_content: str) -> list[dict]:
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": ENTITY_EXTRACT_PROMPT.format(fact=fact_content)}],
        response_format={"type": "json_object"},
        timeout=15,
    )
    return json.loads(response.choices[0].message.content).get("entities", [])

def add_fact_to_graph(fact: dict, user_id: str):
    entities = extract_entities(fact["content"])
    if not entities:
        return

    with driver.session() as session:
        session.run("MERGE (u:User {id: $user_id})", user_id=user_id)
        session.run("""
            MERGE (f:Fact {id: $id})
            SET f.content = $content, f.type = $type,
                f.scope = $scope, f.importance = $importance
            WITH f
            MATCH (u:User {id: $user_id})
            MERGE (u)-[:OWNS]->(f)
        """, id=fact["id"], content=fact["content"], type=fact["type"],
             scope=fact["scope"], importance=fact["importance"], user_id=user_id)

        for entity in entities:
            rel_type = {
                "Person": "INVOLVES", "Project": "PART_OF",
                "Topic": "ABOUT", "Place": "LOCATED_AT",
                "Organization": "INVOLVES",
            }.get(entity["type"], "RELATED_TO")

            session.run(f"""
                MERGE (e:Entity {{name: $name, user_id: $user_id}})
                SET e.entity_type = $entity_type
                WITH e
                MATCH (f:Fact {{id: $fact_id}})
                MERGE (f)-[:{rel_type}]->(e)
            """, name=entity["name"], entity_type=entity["type"],
                 user_id=user_id, fact_id=fact["id"])

        session.run("""
            MATCH (f1:Fact {id: $fact_id})-[]->(e:Entity)<-[]-(f2:Fact)
            WHERE f1 <> f2
            MERGE (f1)-[:RELATED_TO]-(f2)
        """, fact_id=fact["id"])

    log.info("graph_fact_added", fact_id=fact["id"], entities=len(entities))

def query_by_entity(entity_name: str, user_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run("""
            MATCH (u:User {id: $user_id})-[:OWNS]->(f:Fact)-[r]->(e:Entity {user_id: $user_id})
            WHERE toLower(e.name) CONTAINS toLower($name)
            RETURN f.id AS id, f.content AS content, f.type AS type,
                   f.scope AS scope, f.importance AS importance,
                   type(r) AS relationship, e.name AS entity
            ORDER BY f.importance DESC
        """, user_id=user_id, name=entity_name)
        return [dict(r) for r in result]

def query_related_facts(fact_id: str, user_id: str, depth: int = 1) -> list[dict]:
    with driver.session() as session:
        result = session.run(f"""
            MATCH (u:User {{id: $user_id}})-[:OWNS]->(f1:Fact {{id: $fact_id}})
            MATCH (f1)-[:RELATED_TO*1..{depth}]-(f2:Fact)
            MATCH (u)-[:OWNS]->(f2)
            RETURN DISTINCT f2.id AS id, f2.content AS content,
                   f2.type AS type, f2.scope AS scope, f2.importance AS importance
            ORDER BY f2.importance DESC LIMIT 10
        """, user_id=user_id, fact_id=fact_id)
        return [dict(r) for r in result]

def get_entity_graph(user_id: str) -> dict:
    with driver.session() as session:
        nodes = session.run("""
            MATCH (u:User {id: $user_id})-[:OWNS]->(f:Fact)-[]->(e:Entity {user_id: $user_id})
            RETURN DISTINCT e.name AS name, e.entity_type AS type, COUNT(f) AS fact_count
            ORDER BY fact_count DESC
        """, user_id=user_id)
        edges = session.run("""
            MATCH (u:User {id: $user_id})-[:OWNS]->(f:Fact)-[r]->(e:Entity {user_id: $user_id})
            RETURN f.id AS fact_id, f.content AS fact_content,
                   type(r) AS relationship, e.name AS entity
        """, user_id=user_id)
        return {
            "entities": [dict(r) for r in nodes],
            "connections": [dict(r) for r in edges],
        }

def get_top_entities(user_id: str, limit: int = 10) -> list[dict]:
    with driver.session() as session:
        result = session.run("""
            MATCH (u:User {id: $user_id})-[:OWNS]->(f:Fact)-[]->(e:Entity {user_id: $user_id})
            RETURN e.name AS name, e.entity_type AS type, COUNT(f) AS fact_count
            ORDER BY fact_count DESC LIMIT $limit
        """, user_id=user_id, limit=limit)
        return [dict(r) for r in result]

def close():
    driver.close()