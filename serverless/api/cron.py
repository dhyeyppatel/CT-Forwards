"""
serverless/api/cron.py — Vercel Serverless Function entry point for /api/cron.
"""
import sys
from pathlib import Path

_current_dir = Path(__file__).resolve().parent
_serverless_dir = _current_dir.parent
for _p in (_serverless_dir, _serverless_dir / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from lib.config import Config
from lib.database import Database
from lib.telethon_runner import execute_userbot_sync
from api.index import get_context, verify_cron_authorization

app = FastAPI(title="CT-Forwards Cron", redirect_slashes=False)

@app.api_route("/{path:path}", methods=["GET", "POST"])
async def run_cron(request: Request, auth=Depends(verify_cron_authorization)):
    config, db, _, init_error = await get_context()
    if not db:
        return JSONResponse(status_code=503, content={"error": "Database not connected", "detail": init_error})
    result = await execute_userbot_sync(config, db)
    return JSONResponse(content={"status": "completed", "result": result})
