from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    backend_port: int = 8000

    llm_api_key: str = ""
    llm_model: str = "gpt-5.5"
    llm_base_url: str = "https://opencode.ai/zen/v1"
    llm_responses_url: str = "https://opencode.ai/zen/v1/responses"

    use_llm_intent_classifier: bool = True
    llm_intent_classifier_confidence_threshold: float = 0.80
    llm_intent_classifier_low_confidence_threshold: float = 0.50

    # Submission-safe default: keep simple pipeline fast path disabled so
    # pipeline/data-product requests use the full transparent agent workflow.
    # Set ENABLE_SIMPLE_PIPELINE_FAST_PATH=true only for local/product optimization.
    enable_simple_pipeline_fast_path: bool = False

    openhands_workspace_dir: str = "/app/workspace"
    database_url: str = "sqlite:////app/data/pipeforge.db"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def workspace_path(self) -> Path:
        path = Path(self.openhands_workspace_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def responses_url(self) -> str:
        if self.llm_responses_url:
            return self.llm_responses_url

        base = self.llm_base_url.rstrip("/")
        if base.endswith("/responses"):
            return base

        return f"{base}/responses"


settings = Settings()