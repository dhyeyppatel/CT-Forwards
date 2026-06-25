"""
modes/userbot_mode.py — Telethon userbot forwarding.

Reads from source channels without requiring bot membership.
Supports:
  • Album (grouped media) forwarding with album integrity
  • Word replacement, prefix/suffix on text/captions
  • Edit sync — edits in source replicate to all target copies
  • Delete sync — deletions in source remove all target copies
  • FloodWait retry
  • Maintenance mode pause
"""
import asyncio
import logging
from collections import defaultdict

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    MessageNotModifiedError,
    MessageIdInvalidError,
)
from telethon.sessions import StringSession

from forwarder import apply_text_processing, resolve_chat_id, should_skip

logger = logging.getLogger(__name__)

ALBUM_WAIT_SECONDS = 1.5  # debounce window for media groups


async def run_userbot(config, db):
    """Start the Telethon userbot and run until disconnected."""

    # Session
    if config.SESSION_STRING:
        session = StringSession(config.SESSION_STRING)
        logger.info("🔑 Userbot: using SESSION_STRING")
    else:
        session = "userbot_session"
        logger.info("🔑 Userbot: using local session file")

    client = TelegramClient(session, config.API_ID, config.API_HASH)

    # Album buffers: grouped_id → list[Message]
    _album_buf: dict[int, list] = defaultdict(list)
    _album_tasks: dict[int, asyncio.Task] = {}

    # ── Text helpers ──────────────────────────────────────────────────────────

    async def _get_processing_args():
        replacements = await db.get_replacements()
        prefix = await db.get_config("prefix", "")
        suffix = await db.get_config("suffix", "")
        return replacements, prefix, suffix

    async def _process(text: str) -> str:
        replacements, prefix, suffix = await _get_processing_args()
        return apply_text_processing(text, replacements, prefix, suffix)

    # ── Forward a list of messages to all applicable targets ──────────────────

    async def _forward_messages(msgs: list, source_chat_id: int):
        targets = await db.get_targets_for_source(source_chat_id)
        if not targets:
            return

        # Skip check on first message
        first = msgs[0]
        text_raw = getattr(first, "text", "") or getattr(first, "message", "") or ""
        skip_terms = await db.get_skip_terms()
        if should_skip(text_raw, "", skip_terms):
            logger.info(f"⏭️  Skipped msg {first.id} from {source_chat_id}")
            return

        replacements, prefix, suffix = await _get_processing_args()
        needs_edit = bool(replacements or prefix or suffix)

        for target_raw in targets:
            target = resolve_chat_id(target_raw)
            try:
                sent = await client.forward_messages(
                    entity=target,
                    messages=msgs,
                    from_peer=source_chat_id,
                    drop_author=True,
                )
                # Normalise to list
                if not isinstance(sent, list):
                    sent = [sent]

                # Store source→target mapping for edit/delete sync
                for src_msg, tgt_msg in zip(msgs, sent):
                    await db.store_message_map(
                        source_chat_id, src_msg.id, target_raw, tgt_msg.id
                    )

                # Apply text modifications by editing the forwarded copy
                if needs_edit:
                    for src_msg, tgt_msg in zip(msgs, sent):
                        raw = (
                            getattr(src_msg, "text", "")
                            or getattr(src_msg, "message", "")
                            or ""
                        )
                        modified = apply_text_processing(raw, replacements, prefix, suffix)
                        if modified != raw:
                            try:
                                await client.edit_message(target, tgt_msg, text=modified)
                            except (MessageNotModifiedError, MessageIdInvalidError):
                                pass
                            except Exception as edit_err:
                                logger.warning(f"⚠️  Text mod failed: {edit_err}")

                logger.info(
                    f"✅ Forwarded {[m.id for m in msgs]} : {source_chat_id} → {target_raw}"
                )

            except FloodWaitError as e:
                logger.warning(f"⏳ FloodWait {e.seconds}s → {target_raw}")
                await asyncio.sleep(e.seconds)
                # One retry
                try:
                    await client.forward_messages(
                        entity=target,
                        messages=msgs,
                        from_peer=source_chat_id,
                        drop_author=True,
                    )
                except Exception as err:
                    logger.error(f"❌ Retry failed → {target_raw}: {err}")
            except ChannelPrivateError:
                logger.error(f"❌ Private/inaccessible: {target_raw}")
            except Exception as e:
                logger.error(f"❌ Forward error → {target_raw}: {e}")

    # ── Album debounce helper ─────────────────────────────────────────────────

    async def _flush_album(grouped_id: int, source_chat_id: int):
        await asyncio.sleep(ALBUM_WAIT_SECONDS)
        msgs = _album_buf.pop(grouped_id, [])
        _album_tasks.pop(grouped_id, None)
        if msgs:
            msgs.sort(key=lambda m: m.id)
            await _forward_messages(msgs, source_chat_id)

    # ── Event: New message ────────────────────────────────────────────────────

    @client.on(events.NewMessage())
    async def on_new_message(event):
        source_ids = await db.get_all_source_ids()
        if str(event.chat_id) not in source_ids:
            return
        msg = event.message
        if msg.grouped_id:
            gid = msg.grouped_id
            _album_buf[gid].append(msg)
            old = _album_tasks.get(gid)
            if old:
                old.cancel()
            _album_tasks[gid] = asyncio.ensure_future(
                _flush_album(gid, event.chat_id)
            )
        else:
            await _forward_messages([msg], event.chat_id)

    # ── Event: Message edited ─────────────────────────────────────────────────

    @client.on(events.MessageEdited())
    async def on_edit(event):
        source_ids = await db.get_all_source_ids()
        if str(event.chat_id) not in source_ids:
            return

        msg = event.message
        raw = getattr(msg, "text", "") or getattr(msg, "message", "") or ""
        if not raw:
            return  # media-only edit — can't replicate

        modified = await _process(raw)
        targets = await db.get_mapped_targets(event.chat_id, msg.id)

        for t in targets:
            target = resolve_chat_id(t["target_chat_id"])
            try:
                await client.edit_message(target, t["target_msg_id"], text=modified)
                logger.info(
                    f"✏️  Edit synced: {event.chat_id}/{msg.id} → "
                    f"{t['target_chat_id']}/{t['target_msg_id']}"
                )
            except (MessageNotModifiedError, MessageIdInvalidError):
                pass
            except Exception as e:
                logger.error(f"❌ Edit sync failed: {e}")

    # ── Event: Message deleted ────────────────────────────────────────────────

    @client.on(events.MessageDeleted())
    async def on_delete(event):
        if not event.chat_id:
            return
        source_ids = await db.get_all_source_ids()
        if str(event.chat_id) not in source_ids:
            return

        for msg_id in event.deleted_ids:
            targets = await db.get_mapped_targets(event.chat_id, msg_id)
            for t in targets:
                target = resolve_chat_id(t["target_chat_id"])
                try:
                    await client.delete_messages(target, t["target_msg_id"])
                    logger.info(
                        f"🗑️  Delete synced: {event.chat_id}/{msg_id} → "
                        f"{t['target_chat_id']}/{t['target_msg_id']}"
                    )
                except Exception as e:
                    logger.error(f"❌ Delete sync failed: {e}")

    # ── Start ─────────────────────────────────────────────────────────────────

    if config.SESSION_STRING:
        await client.start()
    else:
        await client.start(phone=config.PHONE)
        ss = client.session.save()
        print("\n" + "=" * 60)
        print("📋  SESSION_STRING — paste into Koyeb env vars:")
        print("=" * 60)
        print(ss)
        print("=" * 60 + "\n")

    me = await client.get_me()
    source_count = len(await db.get_all_source_ids())
    logger.info(
        f"🤖 Userbot logged in as {me.first_name} "
        f"(@{me.username or 'N/A'}) | ID: {me.id}"
    )
    logger.info(f"🚀 Userbot running | Sources in DB: {source_count}")

    await client.run_until_disconnected()
