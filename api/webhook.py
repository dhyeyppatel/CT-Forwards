"""
api/webhook.py — Vercel Serverless Function entry point for /api/webhook.
"""
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_root_dir = _current_dir.parent
_serverless_dir = _root_dir / "serverless"
for _p in (_root_dir, _serverless_dir, _serverless_dir / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from telegram import Update
from serverless.api.index import get_context

app = FastAPI(title="CT-Forwards Webhook", redirect_slashes=False)

@app.api_route("/{path:path}", methods=["POST"])
async def telegram_webhook(request: Request):
    config, db, ptb_app, init_error = await get_context()
    if not ptb_app:
        return JSONResponse(
            status_code=503,
            content={"error": "Bot webhook not ready", "detail": init_error or "BOT_TOKEN not configured"},
        )
    try:
        data = await request.json()
        update = Update.de_json(data=data, bot=ptb_app.bot)
        if update:
            await ptb_app.process_update(update)
        return Response(status_code=200, content="OK")
    except Exception as e:
        return Response(status_code=500, content=f"Internal Error: {str(e)}")
