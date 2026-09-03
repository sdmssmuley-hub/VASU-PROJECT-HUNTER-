"""
Central configuration. Loads from .env (never hardcode secrets).
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _list_int(val: str, default: list[int]) -> list[int]:
    if not val:
        return default
    return [int(x.strip()) for x in val.split(",") if x.strip()]


class Settings:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # LLM
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.1")

    # Search
    SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "demo")
    SEARCH_API_KEY: str = os.getenv("SEARCH_API_KEY", "")

    # Dashboard auth
    DASHBOARD_USERNAME: str = os.getenv("DASHBOARD_USERNAME", "owner")
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "change-me")

    # DB
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "./data/vasu.db")

    # Scheduler
    RUN_HOURS: list[int] = _list_int(os.getenv("RUN_HOURS", ""), [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")
    TARGET_LEADS_PER_RUN: int = int(os.getenv("TARGET_LEADS_PER_RUN", "4"))

    # App
    APP_ENV: str = os.getenv("APP_ENV", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Business context (Vasu Engineering) ---
    COMPANY_NAME = "Vasu Engineering"
    PRIMARY_REGIONS = ["Maharashtra"]
    SECONDARY_REGIONS = ["Gujarat"]
    TERTIARY_REGIONS = [
        "Karnataka", "Telangana", "Tamil Nadu", "Odisha",
        "Chhattisgarh", "Jharkhand", "Rajasthan", "Haryana",
        "Uttar Pradesh", "Uttarakhand",
    ]
    TARGET_WINDOW_START = "2026-10"
    TARGET_WINDOW_END = "2027-05"
    HIGH_PRIORITY_MONTHS = ["2026-10", "2026-11", "2026-12"]

    GEO_TIER = {
        "Maharashtra": 1,
        "Gujarat": 2,
        "Karnataka": 3, "Telangana": 3, "Tamil Nadu": 3,
        "Odisha": 3, "Chhattisgarh": 3,
    }


settings = Settings()
