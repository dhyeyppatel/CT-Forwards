"""
serverless/api/setup.py — Vercel Serverless Function entry point for /api/setup.
"""
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_serverless_dir = _current_dir.parent
for _p in (_serverless_dir, _serverless_dir / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from api.index import get_context

app = FastAPI(title="CT-Forwards Setup", redirect_slashes=False)

@app.api_route("/{path:path}", methods=["GET", "POST"])
async def setup_webhook():
    config, db, ptb_app, init_error = await get_context()
    if not config or not config.BOT_TOKEN:
        return JSONResponse(status_code=400, content={"error": "BOT_TOKEN is not set in environment variables."})
    if not config.WEBHOOK_URL:
        return JSONResponse(status_code=400, content={"error": "WEBHOOK_URL is not set.", "hint": "Set WEBHOOK_URL=https://your-deployment.vercel.app"})
    if not ptb_app:
        return JSONResponse(status_code=503, content={"error": "Application not initialized", "detail": init_error})

    webhook_target = f"{config.WEBHOOK_URL.rstrip('/')}/api/webhook"
    try:
        success = await ptb_app.bot.set_webhook(
            url=webhook_target,
            allowed_updates=["message", "edited_message", "channel_post", "edited_channel_post", "callback_query"],
            drop_pending_updates=True,
        )
        info = await ptb_app.bot.get_webhook_info()
        return {
            "success": success,
            "webhook_url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "last_error_message": info.last_error_message,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to set webhook: {str(e)}"})
