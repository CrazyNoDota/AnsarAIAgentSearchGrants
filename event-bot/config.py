from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_allowed_users: str = ""

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "qwen/qwen3-coder-480b-a35b-instruct"
    openai_api_key: str = ""

    database_path: str = "./event_bot.db"
    playwright_browsers_path: str = ""
    headless: bool = True

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
