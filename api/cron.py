"""
api/cron.py — Vercel Serverless Function entry point for /api/cron.
"""
import sys
from pathlib import Path

# Add project root and serverless to sys.path
_current_dir = Path(__file__).resolve().parent
_root_dir = _current_dir.parent
_serverless_dir = _root_dir / "serverless"
for _p in (_root_dir, _serverless_dir, _serverless_dir / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from serverless.api.index import get_context, verify_cron_authorization, execute_userbot_sync

app = FastAPI(title="CT-Forwards Cron", redirect_slashes=False)

@app.api_route("/{path:path}", methods=["GET", "POST"])
async def run_cron(request: Request, auth=Depends(verify_cron_authorization)):
    config, db, _, init_error = await get_context()
    if not db:
        return JSONResponse(status_code=503, content={"error": "Database not connected", "detail": init_error})
    result = await execute_userbot_sync(config, db)
    return JSONResponse(content={"status": "completed", "result": result})
