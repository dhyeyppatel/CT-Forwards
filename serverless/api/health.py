"""
serverless/api/health.py — Vercel Serverless Function entry point for /api/health.
"""
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_serverless_dir = _current_dir.parent
for _p in (_serverless_dir, _serverless_dir / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI
from api.index import get_context

app = FastAPI(title="CT-Forwards Health", redirect_slashes=False)

@app.api_route("/{path:path}", methods=["GET"])
async def health():
    config, db, ptb_app, init_error = await get_context()
    mode = config.MODE if config else "userbot"
    return {
        "status": "healthy" if db else "setup_required",
        "database": "connected" if db else f"disconnected ({init_error})",
        "mode": mode,
        "userbot_configured": bool(config and config.API_ID and config.SESSION_STRING),
        "bot_configured": bool(config and config.BOT_TOKEN),
    }
