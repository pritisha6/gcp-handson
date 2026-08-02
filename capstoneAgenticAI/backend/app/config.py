"""Application configuration loaded from environment variables.

Uses Pydantic settings so required configuration is validated once at
startup rather than failing lazily deep inside request handling.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings sourced from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Environment ---
    ENVIRONMENT: str = Field(default="development", description="development | staging | production")

    # --- Claude / Anthropic ---
    CLAUDE_API_KEY: str = Field(..., description="Anthropic API key used to call Claude models")
    CLAUDE_MODEL: str = Field(default="claude-sonnet-5", description="Default Claude model id")

    # --- GCP ---
    GCP_PROJECT_ID: str = Field(..., description="Google Cloud project id")
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = Field(
        default=None, description="Path to GCP service account JSON credentials"
    )
    FIRESTORE_DATABASE: str = Field(
        default="(default)", description="Firestore database id or full resource path"
    )

    # --- Pinecone ---
    PINECONE_API_KEY: str = Field(..., description="Pinecone API key for the RAG vector store")
    PINECONE_INDEX_NAME: str = Field(default="gcp-designs", description="Pinecone index name")
    PINECONE_CLOUD: str = Field(default="aws", description="Serverless cloud provider for a new index")
    PINECONE_REGION: str = Field(default="us-east-1", description="Serverless region for a new index")

    # --- OpenAI (embeddings) ---
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key used to generate document embeddings")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-large", description="OpenAI embedding model id")
    EMBEDDING_DIMENSIONS: int = Field(default=3072, description="Vector dimensionality of EMBEDDING_MODEL")

    # --- Document chunking ---
    CHUNK_SIZE_TOKENS: int = Field(default=512, description="Target chunk size in tokens")
    CHUNK_OVERLAP_TOKENS: int = Field(default=50, description="Token overlap between consecutive chunks")
    MAX_UPLOAD_FILE_SIZE_MB: int = Field(default=500, description="Maximum accepted size per uploaded file")

    # --- API / server ---
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
    # Kept as a raw string (not List[str]): pydantic-settings attempts a JSON
    # decode of complex-typed env values *before* field validators run, which
    # rejects a plain "*" or comma-separated list. Parse via cors_origins_list.
    CORS_ORIGINS: str = Field(default="*", description="Comma-separated allowed CORS origins, or '*'")
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: Optional[str] = Field(
        default=None, description="'json' or 'text'; defaults to json in production, text otherwise"
    )

    # --- Alerting (Slack / email) ---
    SLACK_WEBHOOK_URL: Optional[str] = Field(default=None, description="Slack incoming webhook URL for alerts")
    ALERT_EMAIL_TO: Optional[str] = Field(default=None, description="Comma-separated alert recipient email addresses")
    ALERT_EMAIL_FROM: Optional[str] = Field(default=None, description="From address for alert emails")
    SMTP_HOST: Optional[str] = Field(default=None, description="SMTP server host for alert emails")
    SMTP_PORT: int = Field(default=587, description="SMTP server port")
    SMTP_USERNAME: Optional[str] = Field(default=None, description="SMTP auth username")
    SMTP_PASSWORD: Optional[str] = Field(default=None, description="SMTP auth password")

    # --- Optional third-party log forwarding ---
    DATADOG_API_KEY: Optional[str] = Field(default=None, description="Datadog API key; enables log forwarding when set")
    DATADOG_SITE: str = Field(default="datadoghq.com", description="Datadog site, e.g. 'datadoghq.eu'")
    SPLUNK_HEC_URL: Optional[str] = Field(default=None, description="Splunk HTTP Event Collector base URL")
    SPLUNK_HEC_TOKEN: Optional[str] = Field(default=None, description="Splunk HEC auth token")

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        allowed = {"development", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}, got {value!r}")
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def alert_email_recipients(self) -> List[str]:
        if not self.ALERT_EMAIL_TO:
            return []
        return [addr.strip() for addr in self.ALERT_EMAIL_TO.split(",") if addr.strip()]

    @property
    def effective_log_format(self) -> str:
        return self.LOG_FORMAT or ("json" if self.is_production else "text")


@lru_cache
def get_settings() -> Settings:
    """Return a cached, validated Settings instance.

    Cached so the environment is parsed and validated exactly once per
    process, while still being overridable in tests via
    ``get_settings.cache_clear()``.
    """
    return Settings()
