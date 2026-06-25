"""
database.py — Async MongoDB layer for Common Thread Auto Forward Bot.

Uses Motor (async MongoDB driver). All runtime configuration is stored here.
On first run, data is seeded from environment variables so existing setups
continue to work without any manual migration.

Collections:
  config        — key/value settings (mode, maintenance, prefix, suffix)
  forward_rules — {source_id, target_ids}
  skip_terms    — {term}
  replace_words — {from_word, to_word}
  message_map   — {source_chat_id, source_msg_id, target_chat_id, target_msg_id}
"""
import logging
import re
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, mongo_url: str, db_name: str = "ct_forwards"):
        self._client = AsyncIOMotorClient(mongo_url)
        self._db = self._client[db_name]

        # Collection references
        self._config = self._db["config"]
        self._rules = self._db["forward_rules"]
        self._skip = self._db["skip_terms"]
        self._replace = self._db["replace_words"]
        self._map = self._db["message_map"]

    async def init(self):
        """Create indexes and verify connection."""
        await self._client.admin.command("ping")

        # Indexes
        await self._config.create_index("key", unique=True)
        await self._skip.create_index("term", unique=True)
        await self._map.create_index(
            [("source_chat_id", 1), ("source_msg_id", 1), ("target_chat_id", 1)],
            unique=True,
        )
        await self._map.create_index("created_at", expireAfterSeconds=604800)  # 7 days TTL

        logger.info("📦 MongoDB connected and indexes ready")

    # ── Config ─────────────────────────────────────────────────────────────

    async def get_config(self, key: str, default: str = "") -> str:
        doc = await self._config.find_one({"key": key})
        return doc["value"] if doc else default

    async def set_config(self, key: str, value: str):
        await self._config.update_one(
            {"key": key},
            {"$set": {"value": str(value)}},
            upsert=True,
        )

    async def delete_config(self, key: str):
        await self._config.delete_one({"key": key})

    # ── Forward Rules ───────────────────────────────────────────────────────

    async def get_rules(self) -> list[dict]:
        cursor = self._rules.find({}, sort=[("_id", 1)])
        out = []
        async for doc in cursor:
            out.append({
                "id": str(doc["_id"]),
                "source_id": doc["source_id"],
                "target_ids": doc["target_ids"],
            })
        return out

    async def add_rule(self, source_id: str, target_ids: list[str]) -> str:
        result = await self._rules.insert_one({
            "source_id": str(source_id),
            "target_ids": [str(t) for t in target_ids],
        })
        return str(result.inserted_id)

    async def delete_rule(self, rule_id: str):
        from bson import ObjectId
        await self._rules.delete_one({"_id": ObjectId(rule_id)})

    async def get_targets_for_source(self, source_chat_id) -> list[str]:
        sid = str(source_chat_id)
        cursor = self._rules.find({"source_id": sid})
        seen: set = set()
        targets: list[str] = []
        async for doc in cursor:
            for t in doc["target_ids"]:
                if t != sid and t not in seen:
                    targets.append(t)
                    seen.add(t)
        return targets

    async def get_all_source_ids(self) -> list[str]:
        cursor = self._rules.find({}, projection={"source_id": 1})
        seen: set = set()
        out: list[str] = []
        async for doc in cursor:
            sid = doc["source_id"]
            if sid not in seen:
                out.append(sid)
                seen.add(sid)
        return out

    # ── Skip Terms ──────────────────────────────────────────────────────────

    async def get_skip_terms(self) -> list[dict]:
        cursor = self._skip.find({}, sort=[("_id", 1)])
        out = []
        async for doc in cursor:
            out.append({"id": str(doc["_id"]), "term": doc["term"]})
        return out

    async def add_skip_term(self, term: str) -> bool:
        try:
            await self._skip.insert_one({"term": term.lower().strip()})
            return True
        except Exception:
            return False  # duplicate

    async def delete_skip_term(self, term_id: str):
        from bson import ObjectId
        await self._skip.delete_one({"_id": ObjectId(term_id)})

    # ── Replace Words ───────────────────────────────────────────────────────

    async def get_replacements(self) -> list[dict]:
        cursor = self._replace.find({}, sort=[("_id", 1)])
        out = []
        async for doc in cursor:
            out.append({
                "id": str(doc["_id"]),
                "from_word": doc["from_word"],
                "to_word": doc["to_word"],
            })
        return out

    async def add_replacement(self, from_word: str, to_word: str) -> str:
        result = await self._replace.insert_one({
            "from_word": from_word.strip(),
            "to_word": to_word.strip(),
        })
        return str(result.inserted_id)

    async def delete_replacement(self, replace_id: str):
        from bson import ObjectId
        await self._replace.delete_one({"_id": ObjectId(replace_id)})

    # ── Message Map ─────────────────────────────────────────────────────────

    async def store_message_map(
        self,
        source_chat_id,
        source_msg_id: int,
        target_chat_id,
        target_msg_id: int,
    ):
        await self._map.update_one(
            {
                "source_chat_id": str(source_chat_id),
                "source_msg_id": source_msg_id,
                "target_chat_id": str(target_chat_id),
            },
            {
                "$set": {
                    "target_msg_id": target_msg_id,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    async def get_mapped_targets(
        self, source_chat_id, source_msg_id: int
    ) -> list[dict]:
        cursor = self._map.find({
            "source_chat_id": str(source_chat_id),
            "source_msg_id": source_msg_id,
        })
        out = []
        async for doc in cursor:
            out.append({
                "target_chat_id": doc["target_chat_id"],
                "target_msg_id": doc["target_msg_id"],
            })
        return out

    # ── First-run seeding from env vars ─────────────────────────────────────

    async def seed_from_config(self, config):
        """Import env-var config into MongoDB on first run (idempotent)."""
        # Mode
        if not await self.get_config("mode"):
            await self.set_config("mode", config.MODE)

        # Maintenance
        if not await self.get_config("maintenance"):
            await self.set_config("maintenance", "false")

        # Forward rules
        existing_rules = await self.get_rules()
        if not existing_rules and config.FORWARD_RULES_RAW:
            from forwarder import parse_rules_raw
            rules = parse_rules_raw(config.FORWARD_RULES_RAW)
            for rule in rules:
                for src in rule["sources"]:
                    await self.add_rule(src, rule["targets"])
            logger.info(f"✅ Seeded {len(rules)} rule(s) from FORWARD_RULES")

        # Skip terms
        existing_skip = await self.get_skip_terms()
        if not existing_skip and config.SKIP_TERMS_RAW:
            terms = [
                t.strip()
                for t in re.split(r"[,;\n]", config.SKIP_TERMS_RAW)
                if t.strip()
            ]
            for term in terms:
                await self.add_skip_term(term)
            logger.info(f"✅ Seeded {len(terms)} skip term(s) from SKIP_TERMS")

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def close(self):
        self._client.close()
        logger.info("📦 MongoDB connection closed")
