"""
telethon_runner.py — On-demand Telethon execution for serverless cron/webhooks.

Instead of keeping a persistent connection open 24/7, this module:
  1. Acquires a distributed MongoDB lock (prevents overlapping cron runs).
  2. Connects Telethon using the stored SESSION_STRING.
  3. Pulls only NEW messages since last_processed_id from all configured source channels.
  4. Preserves album (media group) integrity.
  5. Applies skip terms, word replacements, and prefix/suffix formatting.
  6. Silently forwards to target channels (drop_author=True).
  7. Updates last_processed_id in MongoDB.
  8. Gracefully disconnects and releases the lock.
"""
import asyncio
import logging
import time
from typing import Dict, Any, List

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    MessageNotModifiedError,
    MessageIdInvalidError,
)
from telethon.sessions import StringSession

from lib.forwarder import apply_text_processing, resolve_chat_id, should_skip

logger = logging.getLogger(__name__)

LOCK_NAME = "telethon_cron_lock"
LOCK_TTL = 55  # seconds (cron runs every 60s, so lock expires before next run)


async def execute_userbot_sync(config, db, limit_per_source: int = 50) -> Dict[str, Any]:
    """
    Run one cycle of fetching and forwarding new messages for all sources.
    Safe for serverless execution.
    """
    start_time = time.time()
    stats = {
        "status": "success",
        "sources_checked": 0,
        "messages_forwarded": 0,
        "albums_forwarded": 0,
        "skipped": 0,
        "errors": [],
        "elapsed_seconds": 0.0,
    }

    # 1. Check credentials
    if not (config.API_ID and config.API_HASH and config.SESSION_STRING):
        msg = "Userbot credentials (API_ID, API_HASH, SESSION_STRING) not fully configured"
        logger.warning(msg)
        stats["status"] = "skipped"
        stats["reason"] = msg
        return stats

    # 2. Check maintenance mode
    maintenance = await db.get_config("maintenance", "false")
    if maintenance == "true":
        logger.info("🔒 Maintenance mode active — skipping userbot sync")
        stats["status"] = "maintenance"
        return stats

    # 3. Acquire distributed lock to avoid concurrent cron runs
    lock_acquired = await db.acquire_lock(LOCK_NAME, ttl_seconds=LOCK_TTL)
    if not lock_acquired:
        logger.info("⏳ Another sync run is currently holding the lock. Skipping this invocation.")
        stats["status"] = "locked"
        return stats

    client = None
    try:
        session = StringSession(config.SESSION_STRING)
        client = TelegramClient(session, config.API_ID, config.API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError("SESSION_STRING is invalid or expired. Please regenerate.")

        source_ids = await db.get_all_source_ids()
        stats["sources_checked"] = len(source_ids)

        if not source_ids:
            logger.info("ℹ️ No forward rules configured yet.")
            stats["status"] = "no_sources"
            return stats

        replacements = await db.get_replacements()
        prefix = await db.get_config("prefix", "")
        suffix = await db.get_config("suffix", "")
        skip_terms = await db.get_skip_terms()
        needs_edit = bool(replacements or prefix or suffix)

        for source_raw in source_ids:
            try:
                source_peer = resolve_chat_id(source_raw)
                entity = await client.get_entity(source_peer)
                targets = await db.get_targets_for_source(source_raw)
                if not targets:
                    continue

                last_id = await db.get_last_processed_id(source_raw)

                # Cold-start initialization for new source
                if last_id == 0:
                    latest = await client.get_messages(entity, limit=1)
                    if latest:
                        init_id = latest[0].id
                        await db.set_last_processed_id(source_raw, init_id)
                        logger.info(
                            f"📌 Initialized last_processed_id for {source_raw} to {init_id} "
                            f"(historical messages will not be backfilled)"
                        )
                    continue

                # Fetch all new messages since last_processed_id in chronological order
                messages = await client.get_messages(
                    entity,
                    min_id=last_id,
                    limit=limit_per_source,
                    reverse=True,
                )

                if not messages:
                    continue

                # Group messages into albums (grouped_id) or single items
                groups: List[List[Any]] = []
                current_group: List[Any] = []
                current_gid = None

                for msg in messages:
                    if msg.grouped_id:
                        if current_gid == msg.grouped_id:
                            current_group.append(msg)
                        else:
                            if current_group:
                                groups.append(current_group)
                            current_group = [msg]
                            current_gid = msg.grouped_id
                    else:
                        if current_group:
                            groups.append(current_group)
                            current_group = []
                            current_gid = None
                        groups.append([msg])

                if current_group:
                    groups.append(current_group)

                # Forward each group
                max_processed_id = last_id
                for group in groups:
                    first_msg = group[0]
                    text_raw = (
                        getattr(first_msg, "text", "")
                        or getattr(first_msg, "message", "")
                        or ""
                    )

                    if should_skip(text_raw, "", skip_terms):
                        logger.info(f"⏭️ Skipped msg(s) {[m.id for m in group]} from {source_raw}")
                        stats["skipped"] += len(group)
                        max_processed_id = max(max_processed_id, max(m.id for m in group))
                        continue

                    # Forward to all targets
                    for target_raw in targets:
                        target_peer = resolve_chat_id(target_raw)
                        try:
                            sent = await client.forward_messages(
                                entity=target_peer,
                                messages=group,
                                from_peer=entity,
                                drop_author=True,
                            )

                            if not isinstance(sent, list):
                                sent = [sent]

                            # Store mapping for edit/delete tracking
                            for src_m, tgt_m in zip(group, sent):
                                await db.store_message_map(
                                    source_raw, src_m.id, target_raw, tgt_m.id
                                )

                            # Apply text transformations if requested
                            if needs_edit:
                                for src_m, tgt_m in zip(group, sent):
                                    m_text = (
                                        getattr(src_m, "text", "")
                                        or getattr(src_m, "message", "")
                                        or ""
                                    )
                                    modified = apply_text_processing(
                                        m_text, replacements, prefix, suffix
                                    )
                                    if modified != m_text:
                                        try:
                                            await client.edit_message(
                                                target_peer, tgt_m, text=modified
                                            )
                                        except (
                                            MessageNotModifiedError,
                                            MessageIdInvalidError,
                                        ):
                                            pass
                                        except Exception as e_err:
                                            logger.warning(
                                                f"⚠️ Text modification edit failed: {e_err}"
                                            )

                            if len(group) > 1:
                                stats["albums_forwarded"] += 1
                            stats["messages_forwarded"] += len(group)
                            logger.info(
                                f"✅ Forwarded {[m.id for m in group]} ({source_raw} → {target_raw})"
                            )

                        except FloodWaitError as fe:
                            logger.warning(
                                f"⏳ FloodWait {fe.seconds}s on {target_raw}. Sleeping..."
                            )
                            await asyncio.sleep(min(fe.seconds, 10))
                        except ChannelPrivateError:
                            logger.error(f"❌ Target channel is private or inaccessible: {target_raw}")
                        except Exception as f_err:
                            logger.error(f"❌ Failed to forward to {target_raw}: {f_err}")
                            stats["errors"].append(str(f_err))

                    max_processed_id = max(max_processed_id, max(m.id for m in group))

                # Update checkpoint in database
                if max_processed_id > last_id:
                    await db.set_last_processed_id(source_raw, max_processed_id)

            except Exception as src_err:
                logger.error(f"❌ Error processing source {source_raw}: {src_err}")
                stats["errors"].append(f"Source {source_raw}: {str(src_err)}")

    finally:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        await db.release_lock(LOCK_NAME)

    stats["elapsed_seconds"] = round(time.time() - start_time, 2)
    return stats
