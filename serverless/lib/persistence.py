"""
persistence.py — MongoDB-backed persistence for python-telegram-bot (PTB v21+).

Stores ConversationHandler states and user_data in MongoDB so that
multi-step interactions (add rule, add skip term, etc.) survive across
serverless invocations where each request spins up a fresh process.

Only conversations and user_data are persisted (bot_data, chat_data,
and callback_data are disabled as they are not needed).
"""
import logging
from typing import Dict, Optional

from telegram.ext import BasePersistence, PersistenceInput

logger = logging.getLogger(__name__)


class MongoPersistence(BasePersistence):
    """MongoDB-backed persistence for PTB ConversationHandler."""

    def __init__(self, mongo_db):
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=False,
                user_data=True,
                callback_data=False,
            ),
        )
        self._conversations_col = mongo_db["ptb_conversations"]
        self._user_data_col = mongo_db["ptb_user_data"]

    # ── Key serialization ─────────────────────────────────────────────────
    # PTB conversation keys are tuples like (user_id,) or (user_id, chat_id).
    # MongoDB cannot use tuples as field keys, so we serialize to strings.

    @staticmethod
    def _key_to_str(key) -> str:
        """Serialize a conversation key tuple to a string."""
        if isinstance(key, tuple):
            return "|".join(str(k) for k in key)
        return str(key)

    @staticmethod
    def _str_to_key(s: str):
        """Deserialize a string back to a conversation key tuple."""
        parts = s.split("|")
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                result.append(p)
        return tuple(result)

    # ── Conversations ─────────────────────────────────────────────────────

    async def get_conversations(self, name: str) -> dict:
        """Load all conversation states for a given handler name."""
        cursor = self._conversations_col.find({"handler": name})
        result = {}
        async for doc in cursor:
            key = self._str_to_key(doc["conv_key"])
            result[key] = doc["state"]
        return result

    async def update_conversation(
        self, name: str, key, new_state: Optional[object]
    ) -> None:
        """Update or remove a single conversation state."""
        key_str = self._key_to_str(key)
        if new_state is None:
            await self._conversations_col.delete_one(
                {"handler": name, "conv_key": key_str}
            )
        else:
            await self._conversations_col.update_one(
                {"handler": name, "conv_key": key_str},
                {"$set": {"state": new_state}},
                upsert=True,
            )

    # ── User data ─────────────────────────────────────────────────────────

    async def get_user_data(self) -> Dict[int, dict]:
        """Load all user data."""
        out: Dict[int, dict] = {}
        async for doc in self._user_data_col.find():
            out[doc["user_id"]] = doc.get("data", {})
        return out

    async def update_user_data(self, user_id: int, data: dict) -> None:
        """Persist user data for a specific user."""
        await self._user_data_col.update_one(
            {"user_id": user_id},
            {"$set": {"data": data}},
            upsert=True,
        )

    async def refresh_user_data(self, user_id: int, user_data) -> dict:
        """Return user data as-is (no external refresh needed)."""
        return user_data

    async def drop_user_data(self, user_id: int) -> None:
        """Delete all persisted data for a specific user."""
        await self._user_data_col.delete_one({"user_id": user_id})

    # ── No-ops for disabled data stores ───────────────────────────────────

    async def get_bot_data(self):
        return {}

    async def update_bot_data(self, data) -> None:
        pass

    async def refresh_bot_data(self, bot_data):
        return bot_data

    async def get_chat_data(self) -> dict:
        return {}

    async def update_chat_data(self, chat_id: int, data) -> None:
        pass

    async def refresh_chat_data(self, chat_id: int, chat_data):
        return chat_data

    async def drop_chat_data(self, chat_id: int) -> None:
        pass

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data) -> None:
        pass

    async def flush(self) -> None:
        """No buffering — all writes are immediate."""
        pass
