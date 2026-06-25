"""
management/handlers.py — Admin control panel for Common Thread Auto Forward Bot.

All configuration is done through an interactive Telegram inline-keyboard UI.
Only users whose IDs appear in config.ADMIN_IDS can interact with these handlers.

Menus
─────
/start | /menu  → Main menu
📋 Forward Rules → list, add (source + targets), delete
⚙️ Mode          → switch userbot / bot / both  (restart required)
🚫 Skip Terms    → list, add, delete
🔄 Replace Words → list, add (find → replace), delete
📝 Text Append   → set/clear prefix and suffix per message
🔒 Maintenance   → toggle (restricts bot UI for non-admins, forwarding still works)
📊 Status        → live summary

Note: All messages use HTML parse mode to avoid Telegram MarkdownV1 parse errors.
"""

import logging
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
(
    WAIT_RULE_SOURCE,
    WAIT_RULE_TARGET,
    WAIT_SKIP_TERM,
    WAIT_REPLACE_FROM,
    WAIT_REPLACE_TO,
    WAIT_PREFIX,
    WAIT_SUFFIX,
) = range(7)

END = ConversationHandler.END

# ── Parse mode constant ───────────────────────────────────────────────────────
HTML = "HTML"

# ── Chat name cache (chat_id str → display name str) ────────────────────────
# Populated lazily via bot.get_chat(); persists for the process lifetime.
_chat_name_cache: dict[str, str] = {}


# ── Keyboard builders ─────────────────────────────────────────────────────────

def _kb(*rows):
    """Build InlineKeyboardMarkup from rows of (text, callback_data) pairs."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows]
    )


def _main_kb():
    return _kb(
        [("📋 Forward Rules", "menu_rules"), ("⚙️ Mode", "menu_mode")],
        [("🚫 Skip Terms", "menu_skip"), ("🔄 Replace Words", "menu_replace")],
        [("📝 Text Append", "menu_append"), ("🔒 Maintenance", "menu_maintenance")],
        [("📊 Status", "menu_status")],
    )


# ── Register function (called from main.py) ───────────────────────────────────

def register_handlers(app: Application, config, db):
    """Attach all management handlers to the given PTB Application."""

    admin_ids: set[int] = config.ADMIN_IDS

    # ── Auth guard ────────────────────────────────────────────────────────────

    def admin_only(func):
        """Decorator: reject non-admin interactions gracefully."""
        @wraps(func)
        async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            uid = update.effective_user.id if update.effective_user else None
            if uid not in admin_ids:
                maintenance = await db.get_config("maintenance", "false")
                msg = (
                    "🔒 Bot is in maintenance mode. Please try again later."
                    if maintenance == "true"
                    else "⛔ You are not authorized to use this bot."
                )
                if update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                elif update.effective_message:
                    await update.effective_message.reply_text(msg)
                return END
            return await func(update, ctx)
        return wrapper

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _h(s: str) -> str:
        """Escape a string for safe use inside HTML text."""
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    async def _resolve_name(bot, chat_id: str) -> str:
        """Return the chat title for a given chat_id, falling back to the raw ID.

        Results are cached in _chat_name_cache for the lifetime of the process
        so repeated menu opens don't hammer the Telegram API.
        """
        if chat_id in _chat_name_cache:
            return _chat_name_cache[chat_id]
        try:
            chat = await bot.get_chat(int(chat_id))
            name = chat.title or chat.username or chat_id
        except Exception:
            name = chat_id  # bot not in chat or invalid ID — show raw
        _chat_name_cache[chat_id] = name
        return name

    async def _status_text() -> str:
        rules = await db.get_rules()
        skip = await db.get_skip_terms()
        repl = await db.get_replacements()
        mode = await db.get_config("mode", config.MODE)
        maint = await db.get_config("maintenance", "false")
        prefix = await db.get_config("prefix", "")
        suffix = await db.get_config("suffix", "")
        mode_icon = {"userbot": "🤖", "bot": "🔑", "both": "🔄"}.get(mode, "❓")
        maint_txt = "🔴 ON" if maint == "true" else "🟢 OFF"
        return (
            "📊 <b>Common Thread Auto Forward Bot</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{mode_icon} <b>Mode:</b> <code>{_h(mode)}</code>\n"
            f"📋 <b>Rules:</b> <code>{len(rules)}</code>\n"
            f"🚫 <b>Skip terms:</b> <code>{len(skip)}</code>\n"
            f"🔄 <b>Replacements:</b> <code>{len(repl)}</code>\n"
            f"📌 <b>Prefix:</b> <code>{'set' if prefix else 'none'}</code>\n"
            f"📌 <b>Suffix:</b> <code>{'set' if suffix else 'none'}</code>\n"
            f"🔒 <b>Maintenance:</b> {maint_txt}"
        )

    async def _edit_or_reply(update: Update, text: str, kb=None):
        """Edit existing message if callback, else send new message (always HTML)."""
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(
                    text, reply_markup=kb, parse_mode=HTML
                )
            except Exception:
                pass
        else:
            await update.effective_message.reply_text(
                text, reply_markup=kb, parse_mode=HTML
            )

    # ── Main menu ─────────────────────────────────────────────────────────────

    @admin_only
    async def show_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await _edit_or_reply(update, await _status_text(), _main_kb())
        return END

    @admin_only
    async def show_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        kb = _kb([("◀️ Main Menu", "main_menu")])
        await _edit_or_reply(update, await _status_text(), kb)

    # ── Mode ──────────────────────────────────────────────────────────────────

    @admin_only
    async def show_mode_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        current = await db.get_config("mode", config.MODE)

        def lbl(m):
            return f"{'✅ ' if current == m else ''}{m.capitalize()}"

        kb = _kb(
            [(f"🤖 {lbl('userbot')}", "mode_set:userbot"),
             (f"🔑 {lbl('bot')}", "mode_set:bot")],
            [(f"🔄 {lbl('both')}", "mode_set:both")],
            [("◀️ Back", "main_menu")],
        )
        text = (
            f"⚙️ <b>Mode Settings</b>\n\n"
            f"Current: <code>{_h(current)}</code>\n\n"
            f"<i>Note: mode change takes effect on next restart.</i>"
        )
        await _edit_or_reply(update, text, kb)

    @admin_only
    async def set_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        mode = update.callback_query.data.split(":")[1]
        await db.set_config("mode", mode)
        await update.callback_query.answer(f"✅ Mode set to {mode} (restart to apply)")
        await show_mode_menu(update, ctx)

    # ── Forward Rules ─────────────────────────────────────────────────────────

    @admin_only
    async def show_rules_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        rules = await db.get_rules()
        lines = [f"📋 <b>Forward Rules ({len(rules)})</b>\n{'─' * 28}"]
        for i, r in enumerate(rules, 1):
            src_name = await _resolve_name(ctx.bot, r["source_id"])
            tgt_lines = []
            for t in r["target_ids"]:
                tgt_name = await _resolve_name(ctx.bot, t)
                tgt_lines.append(f"    ➔ <b>{_h(tgt_name)}</b> <code>({_h(t)})</code>")
            lines.append(
                f"<b>Rule {i}</b>\n"
                f"  📥 <b>{_h(src_name)}</b> <code>({_h(r['source_id'])})</code>\n"
                + "\n".join(tgt_lines)
            )
        if not rules:
            lines.append("<i>No rules configured yet.</i>")

        buttons = [[InlineKeyboardButton("➕ Add Rule", callback_data="rules_add")]]
        if rules:
            row: list = []
            for i, r in enumerate(rules, 1):
                row.append(
                    InlineKeyboardButton(f"🗑️ Rule {i}", callback_data=f"rules_del:{r['id']}")
                )
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
        buttons.append([InlineKeyboardButton("◀️ Back", callback_data="main_menu")])

        await _edit_or_reply(update, "\n".join(lines), InlineKeyboardMarkup(buttons))

    @admin_only
    async def delete_rule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        rid = update.callback_query.data.split(":")[1]
        await db.delete_rule(rid)
        await update.callback_query.answer("🗑️ Rule deleted")
        await show_rules_menu(update, ctx)

    @admin_only
    async def start_add_rule(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📋 <b>Add Forward Rule — Step 1 of 2</b>\n\n"
            "Send the <b>SOURCE</b> channel ID:\n"
            "<i>(e.g. -1001234567890)</i>\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_RULE_SOURCE

    async def receive_rule_source(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        ctx.user_data["rule_source"] = update.message.text.strip()
        await update.message.reply_text(
            f"✅ Source: <code>{_h(ctx.user_data['rule_source'])}</code>\n\n"
            "<b>Step 2 of 2</b> — Send the <b>TARGET</b> channel ID(s):\n"
            "<i>Comma-separated for multiple: -1002222,-1003333</i>\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_RULE_TARGET

    async def receive_rule_target(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        targets = [t.strip() for t in update.message.text.strip().split(",") if t.strip()]
        if not targets:
            await update.message.reply_text("❌ No valid IDs found. Try again or /cancel.")
            return WAIT_RULE_TARGET
        source = ctx.user_data.pop("rule_source", "?")
        await db.add_rule(source, targets)
        tgts_str = ", ".join(f"<code>{_h(t)}</code>" for t in targets)
        kb = _kb([("📋 View Rules", "menu_rules"), ("◀️ Menu", "main_menu")])
        await update.message.reply_text(
            f"✅ <b>Rule added!</b>\n\n<code>{_h(source)}</code> ➔ {tgts_str}",
            reply_markup=kb, parse_mode=HTML,
        )
        return END

    # ── Skip Terms ────────────────────────────────────────────────────────────

    @admin_only
    async def show_skip_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        terms = await db.get_skip_terms()
        lines = [f"🚫 <b>Skip Terms ({len(terms)})</b>\n{'─' * 28}"]
        for i, t in enumerate(terms, 1):
            lines.append(f"<b>{i}.</b> <code>{_h(t['term'])}</code>")
        if not terms:
            lines.append("<i>No skip terms configured.</i>")

        buttons = [[InlineKeyboardButton("➕ Add Term", callback_data="skip_add")]]
        if terms:
            row: list = []
            for i, t in enumerate(terms, 1):
                row.append(
                    InlineKeyboardButton(f"🗑️ {i}. {t['term'][:12]}", callback_data=f"skip_del:{t['id']}")
                )
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
        buttons.append([InlineKeyboardButton("◀️ Back", callback_data="main_menu")])

        await _edit_or_reply(update, "\n".join(lines), InlineKeyboardMarkup(buttons))

    @admin_only
    async def delete_skip_term(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tid = update.callback_query.data.split(":")[1]
        await db.delete_skip_term(tid)
        await update.callback_query.answer("🗑️ Skip term removed")
        await show_skip_menu(update, ctx)

    @admin_only
    async def start_add_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🚫 <b>Add Skip Term</b>\n\n"
            "Send the word or phrase to filter:\n"
            "<i>Messages containing this will not be forwarded.</i>\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_SKIP_TERM

    async def receive_skip_term(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        term = update.message.text.strip()
        added = await db.add_skip_term(term)
        kb = _kb([("🚫 Skip Terms", "menu_skip"), ("◀️ Menu", "main_menu")])
        msg = (
            f"✅ Skip term added: <code>{_h(term)}</code>"
            if added
            else f"⚠️ <code>{_h(term)}</code> already exists."
        )
        await update.message.reply_text(msg, reply_markup=kb, parse_mode=HTML)
        return END

    # ── Replace Words ─────────────────────────────────────────────────────────

    @admin_only
    async def show_replace_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        repls = await db.get_replacements()
        lines = [f"🔄 <b>Word Replacements ({len(repls)})</b>\n{'─' * 28}"]
        for i, r in enumerate(repls, 1):
            to = f"<code>{_h(r['to_word'])}</code>" if r["to_word"] else "<i>(deleted)</i>"
            lines.append(f"<b>{i}.</b> <code>{_h(r['from_word'])}</code> ➔ {to}")
        if not repls:
            lines.append("<i>No replacements configured.</i>")

        buttons = [[InlineKeyboardButton("➕ Add Replacement", callback_data="replace_add")]]
        if repls:
            row: list = []
            for i, r in enumerate(repls, 1):
                row.append(
                    InlineKeyboardButton(f"🗑️ {i}. {r['from_word'][:10]}", callback_data=f"replace_del:{r['id']}")
                )
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
        buttons.append([InlineKeyboardButton("◀️ Back", callback_data="main_menu")])

        await _edit_or_reply(update, "\n".join(lines), InlineKeyboardMarkup(buttons))

    @admin_only
    async def delete_replacement(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        rid = update.callback_query.data.split(":")[1]
        await db.delete_replacement(rid)
        await update.callback_query.answer("🗑️ Replacement removed")
        await show_replace_menu(update, ctx)

    @admin_only
    async def start_add_replace(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🔄 <b>Add Word Replacement — Step 1 of 2</b>\n\n"
            "Send the word/phrase to <b>find</b> in messages:\n"
            "<i>Example: Join @old_channel</i>\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_REPLACE_FROM

    async def receive_replace_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        ctx.user_data["replace_from"] = update.message.text.strip()
        await update.message.reply_text(
            f"✅ Will find: <code>{_h(ctx.user_data['replace_from'])}</code>\n\n"
            "<b>Step 2 of 2</b> — Send the <b>replacement</b> text:\n"
            "<i>Example: Join @new_channel</i>\n"
            "<i>Send a single dash (-) to delete the word entirely.</i>\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_REPLACE_TO

    async def receive_replace_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        from_word = ctx.user_data.pop("replace_from", "?")
        to_word = update.message.text.strip()
        if to_word == "-":
            to_word = ""
        await db.add_replacement(from_word, to_word)
        kb = _kb([("🔄 Replacements", "menu_replace"), ("◀️ Menu", "main_menu")])
        to_display = f"<code>{_h(to_word)}</code>" if to_word else "<i>(deleted)</i>"
        await update.message.reply_text(
            f"✅ <b>Replacement added!</b>\n\n<code>{_h(from_word)}</code> ➔ {to_display}",
            reply_markup=kb, parse_mode=HTML,
        )
        return END

    # ── Text Append (prefix / suffix) ────────────────────────────────────────

    @admin_only
    async def show_append_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        prefix = await db.get_config("prefix", "")
        suffix = await db.get_config("suffix", "")
        text = (
            f"📝 <b>Text Append Settings</b>\n{'─' * 28}\n\n"
            f"📌 <b>Prefix</b> <i>(added to start of every message)</i>:\n"
            + (f"<pre>{_h(prefix)}</pre>" if prefix else "<i>not set</i>")
            + "\n\n"
            f"📌 <b>Suffix</b> <i>(added to end of every message)</i>:\n"
            + (f"<pre>{_h(suffix)}</pre>" if suffix else "<i>not set</i>")
        )
        kb = _kb(
            [("✏️ Set Prefix", "append_set_prefix"), ("✏️ Set Suffix", "append_set_suffix")],
            [("🗑️ Clear Prefix", "append_clear_prefix"), ("🗑️ Clear Suffix", "append_clear_suffix")],
            [("◀️ Back", "main_menu")],
        )
        await _edit_or_reply(update, text, kb)

    @admin_only
    async def clear_prefix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await db.delete_config("prefix")
        await update.callback_query.answer("✅ Prefix cleared")
        await show_append_menu(update, ctx)

    @admin_only
    async def clear_suffix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await db.delete_config("suffix")
        await update.callback_query.answer("✅ Suffix cleared")
        await show_append_menu(update, ctx)

    @admin_only
    async def start_set_prefix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📝 <b>Set Prefix</b>\n\n"
            "Send the text to add at the <b>top</b> of every forwarded message:\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_PREFIX

    async def receive_prefix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        val = update.message.text.strip()
        await db.set_config("prefix", val)
        kb = _kb([("📝 Text Settings", "menu_append"), ("◀️ Menu", "main_menu")])
        await update.message.reply_text(
            f"✅ <b>Prefix set!</b>\n\n<pre>{_h(val)}</pre>",
            reply_markup=kb, parse_mode=HTML,
        )
        return END

    @admin_only
    async def start_set_suffix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📝 <b>Set Suffix</b>\n\n"
            "Send the text to add at the <b>bottom</b> of every forwarded message:\n\n"
            "Use /cancel to abort.",
            parse_mode=HTML,
        )
        return WAIT_SUFFIX

    async def receive_suffix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in admin_ids:
            return END
        val = update.message.text.strip()
        await db.set_config("suffix", val)
        kb = _kb([("📝 Text Settings", "menu_append"), ("◀️ Menu", "main_menu")])
        await update.message.reply_text(
            f"✅ <b>Suffix set!</b>\n\n<pre>{_h(val)}</pre>",
            reply_markup=kb, parse_mode=HTML,
        )
        return END

    # ── Maintenance Mode ──────────────────────────────────────────────────────

    @admin_only
    async def show_maintenance_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        maint = await db.get_config("maintenance", "false")
        is_on = maint == "true"
        text = (
            f"🔒 <b>Maintenance Mode</b>\n{'─' * 28}\n\n"
            + (
                "🔴 <b>ON</b> — Non-admins see a maintenance notice when they interact with the bot.\n"
                "<i>Forwarding continues normally. Only the management UI is restricted.</i>"
                if is_on
                else "🟢 <b>OFF</b> — Bot is fully open."
            )
        )
        kb = _kb(
            [("🟢 Turn OFF" if is_on else "🔴 Turn ON", "maintenance_toggle")],
            [("◀️ Back", "main_menu")],
        )
        await _edit_or_reply(update, text, kb)

    @admin_only
    async def toggle_maintenance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        current = await db.get_config("maintenance", "false")
        new_val = "false" if current == "true" else "true"
        await db.set_config("maintenance", new_val)
        label = "ON 🔴" if new_val == "true" else "OFF 🟢"
        await update.callback_query.answer(f"Maintenance {label}")
        await show_maintenance_menu(update, ctx)

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        ctx.user_data.clear()
        await update.effective_message.reply_text(
            "❌ Cancelled.",
            reply_markup=_kb([("◀️ Main Menu", "main_menu")]),
        )
        return END

    # ── Global PTB error handler ──────────────────────────────────────────────

    async def ptb_error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
        logger.error("PTB handler exception:", exc_info=ctx.error)

    # ── Register all handlers ─────────────────────────────────────────────────

    # ConversationHandler for multi-step input flows
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_rule,    pattern="^rules_add$"),
            CallbackQueryHandler(start_add_skip,    pattern="^skip_add$"),
            CallbackQueryHandler(start_add_replace, pattern="^replace_add$"),
            CallbackQueryHandler(start_set_prefix,  pattern="^append_set_prefix$"),
            CallbackQueryHandler(start_set_suffix,  pattern="^append_set_suffix$"),
        ],
        states={
            WAIT_RULE_SOURCE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rule_source)],
            WAIT_RULE_TARGET:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rule_target)],
            WAIT_SKIP_TERM:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_skip_term)],
            WAIT_REPLACE_FROM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_replace_from)],
            WAIT_REPLACE_TO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_replace_to)],
            WAIT_PREFIX:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prefix)],
            WAIT_SUFFIX:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_suffix)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(show_main_menu, pattern="^main_menu$"),
        ],
        per_message=False,
        conversation_timeout=300,   # 5-minute idle timeout
        allow_reentry=True,
    )

    # Error handler (eliminates "No error handlers registered" logs)
    app.add_error_handler(ptb_error_handler)

    # Commands
    app.add_handler(CommandHandler("start",  show_main_menu))
    app.add_handler(CommandHandler("menu",   show_main_menu))
    app.add_handler(CommandHandler("status", show_status))

    # Conversation (registered before bare CallbackQueryHandlers to get priority)
    app.add_handler(conv)

    # Navigation callbacks
    app.add_handler(CallbackQueryHandler(show_main_menu,        pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_status,           pattern="^menu_status$"))
    app.add_handler(CallbackQueryHandler(show_mode_menu,        pattern="^menu_mode$"))
    app.add_handler(CallbackQueryHandler(set_mode,              pattern="^mode_set:"))
    app.add_handler(CallbackQueryHandler(show_rules_menu,       pattern="^menu_rules$"))
    app.add_handler(CallbackQueryHandler(delete_rule,           pattern="^rules_del:"))
    app.add_handler(CallbackQueryHandler(show_skip_menu,        pattern="^menu_skip$"))
    app.add_handler(CallbackQueryHandler(delete_skip_term,      pattern="^skip_del:"))
    app.add_handler(CallbackQueryHandler(show_replace_menu,     pattern="^menu_replace$"))
    app.add_handler(CallbackQueryHandler(delete_replacement,    pattern="^replace_del:"))
    app.add_handler(CallbackQueryHandler(show_append_menu,      pattern="^menu_append$"))
    app.add_handler(CallbackQueryHandler(clear_prefix,          pattern="^append_clear_prefix$"))
    app.add_handler(CallbackQueryHandler(clear_suffix,          pattern="^append_clear_suffix$"))
    app.add_handler(CallbackQueryHandler(show_maintenance_menu, pattern="^menu_maintenance$"))
    app.add_handler(CallbackQueryHandler(toggle_maintenance,    pattern="^maintenance_toggle$"))

    logger.info("✅ Management bot handlers registered")
