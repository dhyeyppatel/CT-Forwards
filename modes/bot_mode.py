"""Bot mode using python-telegram-bot (PTB v21+).

Classic bot approach: the bot must be a member of source channels
and an admin with post permission in target channels.
Uses copyMessage (Bot API) for silent forwarding without "Forwarded From".
"""
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from forwarder import ForwardRules

logger = logging.getLogger(__name__)


def run_bot(config):
    """Start the bot in polling mode (blocking)."""
    rules = ForwardRules(config.FORWARD_RULES_RAW, config.SKIP_TERMS_RAW)

    # ── Command handlers ──────────────────────────────────────────────────

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "✅ *Common Thread Auto Forward Bot is running!*\n\n"
            "This bot silently forwards messages between channels "
            "with no 'Forwarded From' header.\n\n"
            f"📋 *Rules loaded:* {len(rules.rules)}\n"
            f"🚫 *Skip terms:* {len(rules.skip_terms)}\n"
            f"🔁 *Mode:* Bot API\n\n"
            "_Make sure the bot is a member of source channels "
            "and admin in target channels._"
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        sources = rules.get_all_sources()
        text = (
            "📊 *Bot Status*\n\n"
            f"✅ Running\n"
            f"📋 Rules: {len(rules.rules)}\n"
            f"📡 Sources: {len(sources)}\n"
            f"🚫 Skip terms: {len(rules.skip_terms)}\n"
            f"🔑 Token: {'Set ✅' if config.BOT_TOKEN else 'Missing ❌'}\n"
            f"🔁 Mode: Bot API"
        )
        await update.effective_message.reply_text(text, parse_mode="Markdown")

    # ── Channel post handler ──────────────────────────────────────────────

    async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # PTB routes both channel_post and edited_channel_post through MessageHandler
        post = update.channel_post or update.edited_channel_post
        if not post:
            return

        source_id = str(post.chat.id)
        targets = rules.get_targets(source_id)

        if not targets:
            return

        text = post.text or ""
        caption = post.caption or ""

        if rules.should_skip(text, caption):
            logger.info(f"⏭️  Skipped msg {post.message_id} from {source_id}")
            return

        for target_raw in targets:
            target = rules.resolve_chat_id(target_raw)
            try:
                await context.bot.copy_message(
                    chat_id=target,
                    from_chat_id=source_id,
                    message_id=post.message_id,
                )
                logger.info(
                    f"✅ Copied msg {post.message_id}: {source_id} → {target_raw}"
                )
            except Exception as e:
                logger.error(f"❌ Failed to copy to {target_raw}: {e}")

    # ── Build and run the PTB Application ────────────────────────────────

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))

    # Channel posts (new + edited) — ChatType.CHANNEL covers both update types
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL,
            handle_channel_post,
        )
    )

    logger.info(
        f"🤖 Bot mode starting (polling) | "
        f"Rules: {len(rules.rules)} | "
        f"Sources: {len(rules.get_all_sources())}"
    )
    logger.info(
        "⚠️  Reminder: Bot must be a MEMBER of source channels "
        "and ADMIN in target channels."
    )

    app.run_polling(drop_pending_updates=True)
