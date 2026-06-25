"""
Common Thread Auto Forward Bot — Entry Point
=============================================
Runs the management bot (PTB) and/or the Telethon userbot concurrently
using asyncio.gather, sharing a single SQLite database instance.

Supported modes (set via DB/env MODE):
  userbot  → Telethon userbot only
  bot      → PTB bot only (management + forwarding)
  both     → Telethon userbot + PTB bot running simultaneously

BOT_TOKEN is always required for the management interface.
"""
import asyncio
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import Config
from database import Database

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Optional health-check HTTP server ────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok":true,"status":"running"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # suppress HTTP access logs


def _start_health_server(port: int):
    srv = HTTPServer(("0.0.0.0", port), _HealthHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    logger.info(f"🌐 Health-check server listening on port {port}")


# ── PTB async runner ──────────────────────────────────────────────────────────

async def _run_ptb_app(app):
    """Run a PTB Application as an async coroutine (alongside Telethon)."""
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("🤖 PTB bot polling started")
    try:
        # Block until cancelled / gathered task finishes
        await asyncio.Event().wait()
    finally:
        logger.info("🛑 Stopping PTB bot…")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    config = Config()

    try:
        config.validate()
    except AssertionError as exc:
        logger.error(f"❌ Configuration error: {exc}")
        sys.exit(1)

    # ── Database ──────────────────────────────────────────────────────────────
    db = Database(config.MONGO_URL, config.MONGO_DB_NAME)
    await db.init()
    await db.seed_from_config(config)

    # ── Health-check server ───────────────────────────────────────────────────
    if config.PORT:
        _start_health_server(config.PORT)

    # ── Determine active mode ─────────────────────────────────────────────────
    mode = await db.get_config("mode", config.MODE)
    logger.info(f"🚀 Starting Common Thread Auto Forward Bot | Mode: {mode.upper()}")

    tasks: list = []

    # ── PTB Application (management + optional bot forwarding) ────────────────
    if config.BOT_TOKEN:
        from telegram.ext import Application
        from management.handlers import register_handlers as reg_mgmt
        from modes.bot_mode import register_handlers as reg_bot

        ptb_app = Application.builder().token(config.BOT_TOKEN).build()

        # Management panel always registered
        reg_mgmt(ptb_app, config, db)

        # Bot-mode forwarding handlers registered when mode includes "bot"
        if mode in ("bot", "both"):
            reg_bot(ptb_app, config, db)
            logger.info("📡 Bot forwarding: enabled")
        else:
            logger.info("📡 Bot forwarding: disabled (mode is not 'bot' or 'both')")

        tasks.append(_run_ptb_app(ptb_app))
    else:
        logger.warning("⚠️  BOT_TOKEN not set — management bot unavailable")

    # ── Telethon userbot ──────────────────────────────────────────────────────
    has_userbot_creds = bool(
        config.API_ID and config.API_HASH and (config.SESSION_STRING or config.PHONE)
    )

    if mode in ("userbot", "both") and has_userbot_creds:
        from modes.userbot_mode import run_userbot
        tasks.append(run_userbot(config, db))
        logger.info("📡 Userbot forwarding: enabled")
    elif mode in ("userbot", "both") and not has_userbot_creds:
        logger.error(
            "❌ Mode is '%s' but userbot credentials are missing "
            "(need API_ID + API_HASH + SESSION_STRING).", mode
        )

    if not tasks:
        logger.error("❌ Nothing to run. Check your credentials and MODE setting.")
        sys.exit(1)

    try:
        await asyncio.gather(*tasks)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
