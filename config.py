"""Settings, loaded from the .env file next to this script."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# What the assistant calls itself. Match it to your Shortcut's name.
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Friday")

# Secret shared by the iPhone Shortcut and the Mac agent. Anyone with it can use Jarvis.
JARVIS_TOKEN = os.getenv("JARVIS_TOKEN", "")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Tried in order when the main model is busy (503), slow (504) or rate-limited (429) on the free tier.
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.8-flash").split(",") if m.strip()]

# ntfy.sh topic for push notifications (reminders, Claude Code results). Keep it hard to guess.
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

# Ask for a spoken "yes" before sending any message or email.
CONFIRM_BEFORE_SEND = os.getenv("CONFIRM_BEFORE_SEND", "true").lower() != "false"

# Keep listening after each reply so you can carry on talking (true/false).
FOLLOW_UPS = os.getenv("FOLLOW_UPS", "true").lower() != "false"

# Calling again within this many minutes continues the same conversation.
CONVERSATION_IDLE_MINUTES = float(os.getenv("CONVERSATION_IDLE_MINUTES", "15"))

# Where the Mac agent connects to (the cloud server URL, or localhost while testing).
SERVER_URL = os.getenv("JARVIS_SERVER_URL", "http://localhost:8787")

# Folder holding your code projects (for Claude Code).
PROJECTS_DIR = Path(os.path.expanduser(os.getenv("PROJECTS_DIR", "~/Desktop/code")))

# Default country code for phone numbers written without one (e.g. 234). Digits only.
DEFAULT_COUNTRY_CODE = os.getenv("DEFAULT_COUNTRY_CODE", "")

_tz = os.getenv("TIMEZONE")
TZ = ZoneInfo(_tz) if _tz else datetime.now().astimezone().tzinfo


def now() -> datetime:
    return datetime.now(TZ)
