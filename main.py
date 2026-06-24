"""
MN Auto Forward Bot — Entry Point
==================================
Supports two modes:
  MODE=userbot  → Telethon userbot (reads any public channel, no membership needed)
  MODE=bot      → python-telegram-bot polling (bot must be member of source channels)

Optional: Set PORT env var to enable a lightweight health-check HTTP endpoint
(useful for Koyeb Web Service / uptime monitors).
"""
import asyncio
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import Config

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Optional health-check HTTP server ─────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that returns 200 OK for any GET request."""

    def do_GET(self):
        body = b'{"ok": true, "status": "running"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Suppress default HTTP access logs to keep output clean
    def log_message(self, fmt, *args):
        pass


def _start_health_server(port: int):
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"🌐 Health-check server listening on port {port}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config = Config()

    # Validate config before doing anything
    try:
        config.validate()
    except AssertionError as exc:
        logger.error(f"❌ Configuration error: {exc}")
        sys.exit(1)

    # Start optional health-check server (for Koyeb Web Service / uptime monitors)
    if config.PORT:
        _start_health_server(config.PORT)

    mode = config.MODE
    logger.info(f"🚀 Starting MN Auto Forward Bot | Mode: {mode.upper()}")

    if mode == "userbot":
        from modes.userbot_mode import run_userbot
        asyncio.run(run_userbot(config))

    elif mode == "bot":
        from modes.bot_mode import run_bot
        run_bot(config)  # PTB's run_polling() is already blocking


if __name__ == "__main__":
    main()
