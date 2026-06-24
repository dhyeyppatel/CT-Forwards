import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        # ── Mode ──────────────────────────────────────────────────────────────
        self.MODE = os.getenv("MODE", "userbot").lower().strip()

        # ── Userbot settings (Telethon) ───────────────────────────────────────
        api_id_raw = os.getenv("API_ID", "").strip()
        self.API_ID = int(api_id_raw) if api_id_raw.isdigit() else 0
        self.API_HASH = os.getenv("API_HASH", "").strip()
        # SESSION_STRING: generated locally, stored as env var for cloud (Koyeb)
        self.SESSION_STRING = os.getenv("SESSION_STRING", "").strip()
        # PHONE: only needed locally to generate SESSION_STRING for the first time
        self.PHONE = os.getenv("PHONE", "").strip()

        # ── Bot settings (python-telegram-bot) ───────────────────────────────
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

        # ── Common ────────────────────────────────────────────────────────────
        self.FORWARD_RULES_RAW = os.getenv("FORWARD_RULES", "").strip()
        self.SKIP_TERMS_RAW = os.getenv("SKIP_TERMS", "").strip()

        # ── Optional health-check HTTP server port ────────────────────────────
        port_raw = os.getenv("PORT", "").strip()
        self.PORT = int(port_raw) if port_raw.isdigit() else None

        # ── Logging ───────────────────────────────────────────────────────────
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    def validate(self):
        """Raise AssertionError if required variables are missing for the chosen mode."""
        if self.MODE == "userbot":
            assert self.API_ID, (
                "API_ID is required for userbot mode. "
                "Get it from https://my.telegram.org"
            )
            assert self.API_HASH, (
                "API_HASH is required for userbot mode. "
                "Get it from https://my.telegram.org"
            )
            assert self.SESSION_STRING or self.PHONE, (
                "SESSION_STRING (for Koyeb/cloud) or PHONE (for local first-run) "
                "is required for userbot mode. "
                "Run: python generate_session.py"
            )
        elif self.MODE == "bot":
            assert self.BOT_TOKEN, (
                "BOT_TOKEN is required for bot mode. "
                "Get it from @BotFather on Telegram."
            )
        else:
            raise AssertionError(
                f"Unknown MODE='{self.MODE}'. Set MODE=userbot or MODE=bot"
            )

        assert self.FORWARD_RULES_RAW, (
            "FORWARD_RULES must be set. "
            "Example: FORWARD_RULES=-100111111:-100222222"
        )

        logger.info(f"✅ Config validated for {self.MODE.upper()} mode")
