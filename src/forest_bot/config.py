from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# Archive documents count as uploaded on the day the archive was assembled (D13)
ARCHIVE_UPLOADED_AT = datetime(2026, 10, 13, tzinfo=KYIV_TZ)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    database_url: str = "postgresql://forest:forest@localhost:5432/forest"

    groq_answer_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "openai/gpt-oss-20b"

    archive_dir: Path = Path("archive")
    migrations_dir: Path = Path("migrations")
    log_level: str = "INFO"
