from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # VPS
    vps_ip: str = "localhost"

    # Database
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
    telegram_allowed_users: str = ""
    reminder_cron_secret: str = ""

    # NVIDIA AI API (LLM)
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "qwen/qwen3-coder-480b-a35b-instruct"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"

    # NVIDIA Embeddings — separate key. Falls back to nvidia_api_key if empty.
    nvidia_embedding_api_key: str = ""

    # NVIDIA NIM — StepFun multimodal model (Phase 3). Vision-capable; reads
    # scanned/PDF grant calls + user docs via image_url data-URLs (OCR-style).
    # Separate key/model/base_url; key falls back to nvidia_api_key if empty.
    nvidia_step_api_key: str = ""
    nvidia_step_model: str = "stepfun-ai/step-3.7-flash"
    nvidia_step_base_url: str = "https://integrate.api.nvidia.com/v1"

    # Email / SMTP notifications (Phase 4). All optional with safe defaults —
    # email degrades gracefully (log + skip) when unconfigured, mirroring how
    # Telegram checks `telegram_bot_token`. Credentials load from .env ONLY.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True  # STARTTLS (port 587). Set false for plain/SSL.
    smtp_use_ssl: bool = False  # implicit SSL (port 465); mutually exclusive w/ TLS
    email_from: str = ""  # sender address; falls back to smtp_user if empty

    # OpenAI (fallback)
    openai_api_key: str = ""

    # Tavily Search API
    tavily_api_key: str = ""

    # Firecrawl API
    firecrawl_api_key: str = ""

    # Redis
    redis_url: str = "redis://redis:6379"

    # Backend URL (used by bot)
    backend_url: str = "http://localhost:8000"

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            url = self.database_url_override
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
        return bool(self.nvidia_api_key)

    @property
    def embedding_api_key(self) -> str:
        """Dedicated embedding key, falling back to the main NVIDIA key."""
        return self.nvidia_embedding_api_key or self.nvidia_api_key

    @property
    def step_api_key(self) -> str:
        """Dedicated StepFun multimodal key, falling back to the main NVIDIA key."""
        return self.nvidia_step_api_key or self.nvidia_api_key

    @property
    def use_step(self) -> bool:
        return bool(self.step_api_key)

    @property
    def email_sender(self) -> str:
        """Effective From address — explicit `email_from` or the SMTP user."""
        return self.email_from or self.smtp_user

    @property
    def use_email(self) -> bool:
        """Email is usable only when a host AND a sender address are configured."""
        return bool(self.smtp_host and self.email_sender)

    @property
    def use_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def use_tavily(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def use_firecrawl(self) -> bool:
        return bool(self.firecrawl_api_key)

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
