import os
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Database
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5433/corenote",
        description="PostgreSQL connection URL"
    )

    # OpenAI
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # App
    base_url: str = Field(default="http://localhost:8000")
    environment: str = Field(default="development")  # development | production

    # Google OAuth
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")

    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="password123")

    # Cognitive settings
    similarity_threshold: float = 0.85
    scoring_modes: dict = {
        "balanced":   {"similarity": 0.5, "importance": 0.3, "recency": 0.2},
        "planner":    {"similarity": 0.3, "importance": 0.5, "recency": 0.2},
        "executor":   {"similarity": 0.3, "importance": 0.2, "recency": 0.5},
        "researcher": {"similarity": 0.5, "importance": 0.3, "recency": 0.2},
    }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

settings = Settings()