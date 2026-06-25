import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        # ── Mode ──────────────────────────────────────────────────────────────
        # Initial default — may be overridden by DB value at runtime.
        self.MODE = os.getenv("MODE", "userbot").lower().strip()

        # ── Userbot (Telethon) ────────────────────────────────────────────────
        api_id_raw = os.getenv("API_ID", "").strip()
        self.API_ID = int(api_id_raw) if api_id_raw.isdigit() else 0
        self.API_HASH = os.getenv("API_HASH", "").strip()
        self.SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
        self.PHONE = os.getenv("PHONE", "").strip()   # first-run local login only

        # ── Bot (python-telegram-bot) ─────────────────────────────────────────
        # Used for BOTH the management bot and bot-mode forwarding.
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

        # ── Admin IDs ─────────────────────────────────────────────────────────
        # Comma-separated Telegram user IDs that can use the management bot.
        raw_ids = os.getenv("ADMIN_IDS", "").strip()
        self.ADMIN_IDS: set[int] = {
            int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()
        }

        # ── Common (seeded into DB on first run) ──────────────────────────────
        self.FORWARD_RULES_RAW = os.getenv("FORWARD_RULES", "").strip()
        self.SKIP_TERMS_RAW = os.getenv("SKIP_TERMS", "").strip()

        # ── MongoDB ───────────────────────────────────────────────────────────
        self.MONGO_URL = os.getenv("MONGO_URL", "").strip()
        self.MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "ct_forwards").strip()

        # ── Health-check server ───────────────────────────────────────────────
        port_raw = os.getenv("PORT", "").strip()
        self.PORT: int | None = int(port_raw) if port_raw.isdigit() else None

        # ── Logging ───────────────────────────────────────────────────────────
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    def validate(self):
        """Raise AssertionError if the minimum required credentials are missing."""
        has_bot = bool(self.BOT_TOKEN)
        has_userbot = bool(
            self.API_ID and self.API_HASH and (self.SESSION_STRING or self.PHONE)
        )

        assert has_bot or has_userbot, (
            "At least one set of credentials is required:\n"
            "  • BOT_TOKEN  (for bot mode + management bot)\n"
            "  • API_ID + API_HASH + SESSION_STRING  (for userbot mode)\n"
        )

        assert self.MONGO_URL, (
            "MONGO_URL is required. "
            "Set it to your MongoDB connection string."
        )

        if has_bot and not self.ADMIN_IDS:
            logger.warning(
                "⚠️  ADMIN_IDS is not set — no one will be able to use the management bot! "
                "Set ADMIN_IDS=<your_telegram_user_id>"
            )

        logger.info(
            f"✅ Config OK | "
            f"Bot: {'✅' if has_bot else '❌'} | "
            f"Userbot: {'✅' if has_userbot else '❌'} | "
            f"Admins: {len(self.ADMIN_IDS)}"
        )
