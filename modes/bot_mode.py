"""
modes/bot_mode.py — Bot API forwarding mode (python-telegram-bot).

Registers channel-post handlers on a shared PTB Application.
The bot must be a MEMBER of source channels and ADMIN in target channels.

Supports:
  • Silent copy (no "Forwarded From" header)
  • Word replacement, prefix/suffix on text/captions
  • Edit sync for text/caption edits (Bot API supports this)
  • Delete sync: NOT possible via Bot API
  • Maintenance mode pause
"""
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from forwarder import apply_text_processing, resolve_chat_id, should_skip

logger = logging.getLogger(__name__)


def register_handlers(app: Application, config, db):
    """Attach channel-post forwarding handlers to the given Application."""

    # ── Text processing helpers ───────────────────────────────────────────────

    async def _process(text: str) -> str:
        replacements = await db.get_replacements()
        prefix = await db.get_config("prefix", "")
        suffix = await db.get_config("suffix", "")
        return apply_text_processing(text, replacements, prefix, suffix)

    # ── New channel post ──────────────────────────────────────────────────────

    async def handle_channel_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        post = update.channel_post
        if not post:
            return


        source_id = str(post.chat.id)
        targets = await db.get_targets_for_source(source_id)
        if not targets:
            return

        # Skip check
        skip_terms = await db.get_skip_terms()
        if should_skip(post.text or "", post.caption or "", skip_terms):
            logger.info(f"⏭️  Skipped msg {post.message_id} from {source_id}")
            return

        for target_raw in targets:
            target = resolve_chat_id(target_raw)
            try:
                sent = await ctx.bot.copy_message(
                    chat_id=target,
                    from_chat_id=source_id,
                    message_id=post.message_id,
                )
                # Store mapping for edit sync
                await db.store_message_map(source_id, post.message_id, target_raw, sent.message_id)

                # Apply text modifications by editing the copied message
                replacements = await db.get_replacements()
                prefix = await db.get_config("prefix", "")
                suffix = await db.get_config("suffix", "")
                needs_edit = bool(replacements or prefix or suffix)

                if needs_edit:
                    raw = post.text or post.caption or ""
                    modified = apply_text_processing(raw, replacements, prefix, suffix)
                    if modified != raw:
                        try:
                            if post.text is not None:
                                # Pure text message
                                await ctx.bot.edit_message_text(
                                    chat_id=target,
                                    message_id=sent.message_id,
                                    text=modified or " ",
                                )
                            else:
                                # Media message — set/update caption
                                await ctx.bot.edit_message_caption(
                                    chat_id=target,
                                    message_id=sent.message_id,
                                    caption=modified,
                                )
                        except Exception as edit_err:
                            logger.warning(f"Text modification failed: {edit_err}")

                logger.info(f"✅ Copied msg {post.message_id}: {source_id} → {target_raw}")

            except Exception as e:
                logger.error(f"❌ Failed to copy to {target_raw}: {e}")

    # ── Edited channel post ───────────────────────────────────────────────────

    async def handle_edited_channel_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        post = update.edited_channel_post
        if not post:
            return

        # Get mapped target messages
        targets = await db.get_mapped_targets(post.chat.id, post.message_id)
        if not targets:
            return

        raw = post.text or post.caption or ""
        modified = await _process(raw) if raw else ""

        for t in targets:
            target = resolve_chat_id(t["target_chat_id"])
            try:
                if post.text and modified:
                    await ctx.bot.edit_message_text(
                        chat_id=target,
                        message_id=t["target_msg_id"],
                        text=modified,
                    )
                elif post.caption is not None:
                    await ctx.bot.edit_message_caption(
                        chat_id=target,
                        message_id=t["target_msg_id"],
                        caption=modified,
                    )
                logger.info(
                    f"✏️  Edit synced: {post.chat.id}/{post.message_id} → "
                    f"{t['target_chat_id']}/{t['target_msg_id']}"
                )
            except Exception as e:
                logger.error(f"❌ Edit sync error → {t['target_chat_id']}: {e}")

    # ── Register ──────────────────────────────────────────────────────────────

    app.add_handler(
        MessageHandler(filters.ChatType.CHANNEL & ~filters.UpdateType.EDITED_CHANNEL_POST,
                       handle_channel_post)
    )
    app.add_handler(
        MessageHandler(filters.UpdateType.EDITED_CHANNEL_POST,
                       handle_edited_channel_post)
    )

    logger.info("✅ Bot forwarding handlers registered")
