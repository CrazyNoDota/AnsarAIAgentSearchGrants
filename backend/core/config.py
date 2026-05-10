from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Database — DATABASE_URL takes precedence (Supabase / production).
    # POSTGRES_* fields are kept for local docker-compose dev only.
    database_url_override: str = Field(default="", alias="DATABASE_URL")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "grants_db"
    postgres_user: str = "grants_user"
    postgres_password: str = "changeme"

    # JWT
    secret_key: str = "change-this-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    # Admin seed
    admin_username: str = "admin"
    admin_password: str = "changeme123"

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_users: str = ""  # comma-separated user IDs

    # OpenAI
    openai_api_key: str = ""

    # NVIDIA AI API (OpenAI-compatible — Qwen3-Coder 480B)
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "qwen/qwen3-coder-480b-a35b-instruct"

    # Backend URL (used internally by bot container)
    backend_url: str = "http://localhost:8000"

    # Comma-separated list of allowed CORS origins for the API
    cors_origins: str = "http://localhost:3000"

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            url = self.database_url_override
            # Normalise standard postgres scheme to asyncpg driver
            if url.startswith("postgresql://"):
                url = "postgresql+asyncpg://" + url[len("postgresql://"):]
            elif url.startswith("postgres://"):
                url = "postgresql+asyncpg://" + url[len("postgres://"):]
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def use_nvidia_ai(self) -> bool:
        """True if NVIDIA API is configured (preferred over OpenAI)."""
        return bool(self.nvidia_api_key)

    @property
    def use_openai(self) -> bool:
        """True if OpenAI API is configured."""
        return bool(self.openai_api_key)

    @property
    def allowed_user_ids(self) -> list[int]:
        if not self.telegram_allowed_users:
            return []
        return [
            int(uid.strip())
            for uid in self.telegram_allowed_users.split(",")
            if uid.strip().lstrip("-").isdigit()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
