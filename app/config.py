import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    database_url: str
    encryption_key: str
    debug: bool = False

def load_settings() -> Settings:
    required = ("BOT_TOKEN", "OWNER_ID", "DATABASE_URL", "ENCRYPTION_KEY")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    try:
        owner_id = int(os.environ["OWNER_ID"])
    except ValueError as exc:
        raise RuntimeError("OWNER_ID must be a numeric Telegram user ID") from exc
    return Settings(
        bot_token=os.environ["BOT_TOKEN"].strip(),
        owner_id=owner_id,
        database_url=os.environ["DATABASE_URL"].strip(),
        encryption_key=os.environ["ENCRYPTION_KEY"].strip(),
        debug=os.getenv("DEBUG", "0").strip() == "1",
    )
