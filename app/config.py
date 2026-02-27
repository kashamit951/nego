from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_corpus_root() -> str:
    # Resolve to repository root (parent of `app`) on the current machine.
    return str(Path(__file__).resolve().parents[1])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEGO_", extra="ignore")

    app_name: str = "Multi-Tenant Contract AI"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/nego"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    corpus_allowed_roots: str = _default_corpus_root()
    corpus_max_scan_files: int = 15000

    auth_enabled: bool = True
    auth_key_pepper: str = "change-me"
    auth_bootstrap_token: str | None = None

    llm_provider: str = "openai_compatible"
    llm_model: str = "llama3"
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 60.0

    clause_classifier_provider: str = "keyword"
    clause_classifier_artifact_path: str | None = None
    embedding_provider: str = "deterministic"
    embedding_model_name: str = "all-MiniLM-L6-v2"
    default_top_k: int = 8
    embedding_dim: int = 384
    acceptance_model_provider: str = "baseline"
    acceptance_model_artifact_path: str | None = None

    enable_autocreate_schema: bool = False

    def assert_llm_only(self) -> None:
        if self.llm_provider.lower() != "openai_compatible":
            raise ValueError("NEGO_LLM_PROVIDER must be openai_compatible for LLM-only mode.")
        if not self.llm_api_base:
            raise ValueError("NEGO_LLM_API_BASE is required for LLM-only mode.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
