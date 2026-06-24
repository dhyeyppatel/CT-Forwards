"""Userbot mode using Telethon (MTProto).

The userbot can read from ANY public channel without being a member,
and any private channel/group it has joined as a regular user.
"""
import asyncio
import logging
from collections import defaultdict

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ChannelPrivateError
from telethon.sessions import StringSession

from forwarder import ForwardRules

logger = logging.getLogger(__name__)

# Album (grouped message) collector:
# grouped_id -> list of messages, used to forward full albums together.
_album_buffer: dict = defaultdict(list)
_album_timers: dict = {}

ALBUM_WAIT_SECONDS = 1.5  # wait this long after first msg in album before forwarding


async def run_userbot(config):
    rules = ForwardRules(config.FORWARD_RULES_RAW, config.SKIP_TERMS_RAW)
    all_sources = rules.get_all_sources()

    # Convert source IDs to int where possible (Telethon needs int for channel IDs)
    source_ids = []
    for s in all_sources:
        stripped = s.lstrip("-")
        source_ids.append(int(s) if stripped.isdigit() else s)

    if not source_ids:
        logger.error("❌ No valid source IDs found in FORWARD_RULES. Exiting.")
        return

    # Choose session type
    if config.SESSION_STRING:
        session = StringSession(config.SESSION_STRING)
        logger.info("🔑 Using SESSION_STRING (cloud mode)")
    else:
        session = "userbot_session"  # saves userbot_session.session locally
        logger.info("🔑 Using local session file (userbot_session.session)")

    client = TelegramClient(session, config.API_ID, config.API_HASH)

    # ── Core forwarding helper ─────────────────────────────────────────────

    async def do_forward(messages: list, source_id):
        """Forward a list of messages (album or single) to all target chats."""
        targets = rules.get_targets(source_id)
        if not targets:
            return

        # Skip check on the first (or only) message
        first = messages[0]
        text = getattr(first, "text", "") or ""
        caption = getattr(first, "message", "") or ""
        if rules.should_skip(text, caption):
            logger.info(f"⏭️  Skipped msg(s) from {source_id}")
            return

        for target_raw in targets:
            target = rules.resolve_chat_id(target_raw)
            try:
                await client.forward_messages(
                    entity=target,
                    messages=messages,
                    from_peer=source_id,
                    drop_author=True,
                )
                ids = [m.id for m in messages]
                logger.info(f"✅ Forwarded {ids} : {source_id} → {target_raw}")
            except FloodWaitError as e:
                logger.warning(f"⏳ FloodWait {e.seconds}s before retrying {target_raw}")
                await asyncio.sleep(e.seconds)
                # Retry once after flood wait
                try:
                    await client.forward_messages(
                        entity=target,
                        messages=messages,
                        from_peer=source_id,
                        drop_author=True,
                    )
                    logger.info(f"✅ Forwarded (retry): {source_id} → {target_raw}")
                except Exception as retry_err:
                    logger.error(f"❌ Retry failed {target_raw}: {retry_err}")
            except ChannelPrivateError:
                logger.error(
                    f"❌ Cannot access {target_raw} — private channel or not a member"
                )
            except Exception as e:
                logger.error(f"❌ Failed to forward to {target_raw}: {e}")

    # ── Album (grouped media) handling ─────────────────────────────────────

    async def flush_album(grouped_id: int, source_id: int):
        """Called after ALBUM_WAIT_SECONDS to forward collected album messages."""
        await asyncio.sleep(ALBUM_WAIT_SECONDS)
        msgs = _album_buffer.pop(grouped_id, [])
        _album_timers.pop(grouped_id, None)
        if msgs:
            msgs.sort(key=lambda m: m.id)
            await do_forward(msgs, source_id)

    async def handle_message_event(event, is_edit: bool = False):
        """Unified handler for new messages and edited messages."""
        msg = event.message
        source_id = event.chat_id

        # Album / media group handling
        if msg.grouped_id:
            gid = msg.grouped_id
            _album_buffer[gid].append(msg)
            # Cancel existing timer and restart (debounce)
            old_task = _album_timers.get(gid)
            if old_task:
                old_task.cancel()
            _album_timers[gid] = asyncio.ensure_future(
                flush_album(gid, source_id)
            )
            return

        # Single message
        await do_forward([msg], source_id)

    # ── Register Telethon event handlers ──────────────────────────────────

    @client.on(events.NewMessage(chats=source_ids))
    async def on_new_message(event):
        await handle_message_event(event, is_edit=False)

    @client.on(events.MessageEdited(chats=source_ids))
    async def on_edited_message(event):
        # Re-forward edited messages (appears as a new message in target)
        await handle_message_event(event, is_edit=True)

    # ── Start the client ──────────────────────────────────────────────────

    if config.SESSION_STRING:
        await client.start()
    else:
        # First-time local login — will prompt for phone + OTP
        await client.start(phone=config.PHONE)
        session_str = client.session.save()
        print("\n" + "=" * 60)
        print("📋  SESSION_STRING — copy this into Koyeb env vars:")
        print("=" * 60)
        print(session_str)
        print("=" * 60 + "\n")
        logger.info("SESSION_STRING printed above. Set it as SESSION_STRING in Koyeb.")

    me = await client.get_me()
    logger.info(
        f"🤖 Logged in as: {me.first_name} "
        f"(@{me.username or 'no_username'}) | ID: {me.id}"
    )
    logger.info(
        f"🚀 Userbot running | "
        f"Watching {len(source_ids)} source(s) | "
        f"Rules: {len(rules.rules)}"
    )

    await client.run_until_disconnected()
