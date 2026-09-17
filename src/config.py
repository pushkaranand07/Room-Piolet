# src/config.py
"""Configuration file for the booking agent."""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta, datetime

# Load Environment Variables

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / '.env', override=True)

# App
PROJECT_NAME = os.environ["PROJECT_NAME"]
FLASK_SECRET_KEY = os.environ["FLASK_SECRET_KEY"]

# LLM Configuration
TEMPERATURE = float(os.environ["TEMPERATURE"])
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_MODEL_NAME = os.environ["GROQ_MODEL_NAME"]
# 4.2 — Groq retry / timeout (configurable via .env)
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "6"))
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "60"))

# Gemini config (free tier via Google AI Studio)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

# Provider selector: "groq" | "gemini" | "fake"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

# LangSmith Configuration
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false")
LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")

# File Paths
ROOMS_FILE = PROJECT_DIR / "data/rooms.json"
BOOKINGS_FILE = PROJECT_DIR / "data/bookings.json"
MSG_JSON_FILE = PROJECT_DIR / "data/clarification_messages.json"
LOGS_DIR = PROJECT_DIR / "logs"

# 4.4 — Timezone: deterministic "today / tomorrow" date math
SERVER_TIMEZONE = os.getenv("SERVER_TIMEZONE", "Asia/Kolkata")

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore  # Python < 3.9

_TZ = ZoneInfo(SERVER_TIMEZONE)


def now_local() -> datetime:
    """Return the current datetime in the configured server timezone (TZ-aware)."""
    return datetime.now(_TZ)


# Logging Configuration
recursion_limit = 50
# sys.setrecursionlimit(recursion_limit)
DELAY = timedelta(hours=0.5)

# Ensure logs directory exists
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Create log file with current date
current_time = datetime.now().strftime('%Y-%m-%d_%H')
log_file_path = LOGS_DIR / f"{current_time}.log"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


class FlaskConfig:
    """Flask application configuration."""
    FLASK_APP = os.getenv('FLASK_APP', 'src.app')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
    DEBUG = os.getenv('FLASK_DEBUG', '1') == '1'
    PORT = os.getenv('PORT', '5000')
    HOST = os.getenv('HOST', '127.0.0.1')
    PERMANENT_SESSION_LIFETIME = timedelta(hours=5)