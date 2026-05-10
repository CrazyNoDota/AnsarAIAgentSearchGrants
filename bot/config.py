from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_users: str = ""
    backend_url: str = "http://backend:8000"

    # JWT for backend API calls
    admin_username: str = "admin"
    admin_password: str = "changeme123"

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
def get_bot_settings() -> BotSettings:
    return BotSettings()
