"""
api/index.py — Serverless ASGI entry point for CT-Forwards on Vercel / serverless.

Endpoints:
  • GET  /                    — Dashboard & status
  • GET  /api/health          — Health check
  • POST /api/webhook         — Telegram Bot API Webhook (admin panel + bot mode)
  • GET  /api/cron            — Vercel Cron job (triggers Telethon userbot pull & forward)
  • POST /api/trigger-userbot — On-demand userbot execution endpoint
  • GET  /api/setup           — Webhook registration helper (calls Telegram setWebhook)
"""
import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Header, Query
from fastapi.responses import JSONResponse, HTMLResponse
from telegram import Update
from telegram.ext import Application

from lib.config import Config
from lib.database import Database
from lib.persistence import MongoPersistence
from lib.telethon_runner import execute_userbot_sync
from modes import bot_mode
from management import handlers

logger = logging.getLogger("serverless_api")

app = FastAPI(
    title="CT-Forwards Serverless",
    description="Serverless Telegram Auto Forward Bot (Webhook + Cron Driven)",
    version="2.0.0",
)

# ── Global Cached Instances (Reused across warm serverless invocations) ──────
_config: Optional[Config] = None
_db: Optional[Database] = None
_ptb_app: Optional[Application] = None
_init_lock = asyncio.Lock()


async def get_context():
    """
    Lazy initialization of Config, Database, and PTB Application.
    Ensures safe initialization across concurrent invocations.
    """
    global _config, _db, _ptb_app

    if _config is not None and _db is not None and (_ptb_app is not None or not _config.BOT_TOKEN):
        return _config, _db, _ptb_app

    async with _init_lock:
        if _config is None:
            _config = Config()

        if _db is None:
            _db = Database(_config.MONGO_URL, _config.MONGO_DB_NAME)
            await _db.init()
            await _db.seed_from_config(_config)

        if _ptb_app is None and _config.BOT_TOKEN:
            persistence = MongoPersistence(_db._db)
            _ptb_app = (
                Application.builder()
                .token(_config.BOT_TOKEN)
                .persistence(persistence)
                .build()
            )
            # Register Bot forwarding mode
            bot_mode.register_handlers(_ptb_app, _config, _db)
            # Register Management Admin panel
            handlers.register_handlers(_ptb_app, _config, _db)

            await _ptb_app.initialize()
            await _ptb_app.start()
            logger.info("🤖 PTB Webhook Application initialized and started")

    return _config, _db, _ptb_app


def verify_cron_authorization(
    authorization: Optional[str] = Header(None),
    x_cron_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
):
    """Verify incoming cron or webhook trigger authentication."""
    expected_secret = os.getenv("CRON_SECRET", "").strip()
    if not expected_secret:
        return True  # No secret configured, allow access

    # Check Bearer token (Vercel standard)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
        if token == expected_secret:
            return True

    # Check custom header or query param (?secret=... or ?key=...)
    provided_secret = x_cron_secret or secret or key
    if provided_secret == expected_secret:
        return True

    raise HTTPException(status_code=401, detail="Unauthorized: Invalid cron secret")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    config, db, ptb_app = await get_context()
    mode = await db.get_config("mode", config.MODE)
    rules = await db.get_rules()
    maint = await db.get_config("maintenance", "false")
    userbot_ready = bool(config.API_ID and config.API_HASH and config.SESSION_STRING)
    bot_ready = bool(config.BOT_TOKEN)

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>CT-Forwards Serverless Status</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px 20px; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
            h1 {{ margin-top: 0; color: #38bdf8; font-size: 24px; }}
            .badge {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 13px; font-weight: 600; margin-bottom: 20px; }}
            .badge-active {{ background: #065f46; color: #34d399; }}
            .badge-maint {{ background: #991b1b; color: #f87171; }}
            .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 24px 0; }}
            .card {{ background: #0f172a; padding: 16px; border-radius: 8px; border: 1px solid #334155; }}
            .card h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #94a3b8; text-transform: uppercase; }}
            .card p {{ margin: 0; font-size: 18px; font-weight: bold; color: #f1f5f9; }}
            .endpoints {{ background: #0f172a; padding: 16px; border-radius: 8px; font-family: monospace; font-size: 13px; }}
            .endpoints li {{ margin-bottom: 8px; }}
            code {{ color: #38bdf8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔁 CT-Forwards Serverless</h1>
            <span class="badge {'badge-maint' if maint == 'true' else 'badge-active'}">
                {'🔒 MAINTENANCE ACTIVE' if maint == 'true' else '🟢 OPERATIONAL'}
            </span>
            <div class="grid">
                <div class="card">
                    <h3>Active Mode</h3>
                    <p>{mode.upper()}</p>
                </div>
                <div class="card">
                    <h3>Forward Rules</h3>
                    <p>{len(rules)}</p>
                </div>
                <div class="card">
                    <h3>Userbot Credentials</h3>
                    <p>{'✅ Configured' if userbot_ready else '❌ Missing'}</p>
                </div>
                <div class="card">
                    <h3>Bot Webhook</h3>
                    <p>{'✅ Configured' if bot_ready else '❌ Missing'}</p>
                </div>
            </div>
            <h3>Serverless Endpoints</h3>
            <div class="endpoints">
                <ul>
                    <li><code>POST /api/webhook</code> — Telegram Bot API Webhook</li>
                    <li><code>GET /api/cron</code> — Vercel Cron Trigger (Telethon userbot)</li>
                    <li><code>POST /api/trigger-userbot</code> — On-demand userbot execution</li>
                    <li><code>GET /api/setup</code> — Register Webhook with Telegram</li>
                    <li><code>GET /api/health</code> — JSON Health Check</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/api/health")
async def health_check():
    config, db, ptb_app = await get_context()
    mode = await db.get_config("mode", config.MODE)
    maintenance = await db.get_config("maintenance", "false")
    return {
        "status": "healthy",
        "mode": mode,
        "maintenance": maintenance == "true",
        "userbot_configured": bool(config.API_ID and config.SESSION_STRING),
        "bot_configured": bool(config.BOT_TOKEN),
    }


@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """
    Receives Telegram Bot updates via Webhook.
    Dispatches to PTB handlers (Bot mode forwarding + Admin panel).
    """
    config, db, ptb_app = await get_context()

    if not ptb_app:
        return JSONResponse(
            status_code=400,
            content={"error": "BOT_TOKEN not configured; webhook processing disabled"},
        )

    try:
        data = await request.json()
        update = Update.de_json(data=data, bot=ptb_app.bot)
        if update:
            await ptb_app.process_update(update)
        return Response(status_code=200, content="OK")
    except Exception as e:
        logger.error(f"Error handling Telegram webhook update: {e}", exc_info=True)
        return Response(status_code=500, content="Internal Error")


@app.api_route("/api/cron", methods=["GET", "POST"])
async def cron_userbot_sync(
    request: Request,
    auth=Depends(verify_cron_authorization),
):
    """
    Scheduled cron endpoint (e.g. Vercel Cron every 1 minute).
    Connects Telethon with StringSession, fetches new messages, forwards, and disconnects.
    """
    config, db, _ = await get_context()
    result = await execute_userbot_sync(config, db)
    return JSONResponse(content={"status": "completed", "result": result})


@app.api_route("/api/trigger-userbot", methods=["GET", "POST"])
async def trigger_userbot(
    request: Request,
    auth=Depends(verify_cron_authorization),
):
    """
    On-demand webhook trigger for executing the userbot forwarding cycle immediately.
    """
    config, db, _ = await get_context()
    result = await execute_userbot_sync(config, db)
    return JSONResponse(content={"status": "completed", "result": result})


@app.get("/api/setup")
async def setup_webhook():
    """
    Helper to set the Telegram Bot webhook URL.
    Uses WEBHOOK_URL from environment variables or returns instructions.
    """
    config, db, ptb_app = await get_context()

    if not config.BOT_TOKEN:
        return JSONResponse(
            status_code=400,
            content={"error": "BOT_TOKEN is not set in environment variables."},
        )

    if not config.WEBHOOK_URL:
        return JSONResponse(
            status_code=400,
            content={
                "error": "WEBHOOK_URL is not set in environment variables.",
                "hint": "Set WEBHOOK_URL=https://your-deployment-url.vercel.app",
            },
        )

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
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to set webhook: {str(e)}"},
        )
