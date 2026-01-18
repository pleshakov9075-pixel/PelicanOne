from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    genapi_base_url: str = Field(alias="GENAPI_BASE_URL")
    genapi_token: str = Field(alias="GENAPI_TOKEN")
    api_public_base_url: str = Field(
        alias="API_PUBLIC_BASE_URL",
        default="http://localhost:8000",
    )
    yookassa_shop_id: str = Field(alias="YOOKASSA_SHOP_ID")
    yookassa_secret_key: str = Field(alias="YOOKASSA_SECRET_KEY")
    admin_ids: str = Field(alias="ADMIN_IDS", default="")
    max_output_tokens: int = Field(alias="MAX_OUTPUT_TOKENS", default=1024)
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")

    def admin_id_set(self) -> set[int]:
        if not self.admin_ids:
            return set()
        return {int(item.strip()) for item in self.admin_ids.split(",") if item.strip()}


settings = Settings()
