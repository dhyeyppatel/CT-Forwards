import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class ForwardRules:
    """
    Parses and stores forwarding rules and skip terms.

    FORWARD_RULES format (same as original, backward-compatible):
        SOURCE:TARGET
        SOURCE:TARGET1,TARGET2
        SOURCE1,SOURCE2:TARGET
        RULE1;RULE2;RULE3

    Examples:
        -100111111:-100222222
        -100111111:-100222222,-100333333
        -100111111,-100222222:-100333333
        -100111111:-100222222;-100444444:-100555555
    """

    def __init__(self, rules_raw: str, skip_terms_raw: str = ""):
        self.rules = self._parse_rules(rules_raw)
        self.skip_terms = self._parse_skip_terms(skip_terms_raw)
        self._log_summary()

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_rules(self, raw: str) -> list:
        rules = []
        for segment in str(raw or "").split(";"):
            segment = segment.strip()
            if not segment or ":" not in segment:
                continue
            colon = segment.index(":")
            left = segment[:colon].strip()
            right = segment[colon + 1:].strip()
            sources = [s.strip() for s in left.split(",") if s.strip()]
            targets = [t.strip() for t in right.split(",") if t.strip()]
            if sources and targets:
                rules.append({"sources": sources, "targets": targets})
        return rules

    def _parse_skip_terms(self, raw: str) -> List[str]:
        return [
            t.strip().lower()
            for t in re.split(r"[,;\n]", str(raw or ""))
            if t.strip()
        ]

    def _log_summary(self):
        logger.info(
            f"📋 Rules: {len(self.rules)} | "
            f"Sources: {len(self.get_all_sources())} | "
            f"Skip terms: {len(self.skip_terms)}"
        )

    # ── Lookups ───────────────────────────────────────────────────────────────

    def get_targets(self, source_chat_id) -> List[str]:
        """Return list of target chat IDs for a given source ID."""
        sid = str(source_chat_id)
        seen: set = set()
        targets: List[str] = []
        for rule in self.rules:
            if sid in rule["sources"]:
                for t in rule["targets"]:
                    if t != sid and t not in seen:
                        targets.append(t)
                        seen.add(t)
        return targets

    def get_all_sources(self) -> List[str]:
        """Return deduplicated list of all configured source IDs."""
        seen: set = set()
        sources: List[str] = []
        for rule in self.rules:
            for s in rule["sources"]:
                if s not in seen:
                    sources.append(s)
                    seen.add(s)
        return sources

    # ── Filtering ─────────────────────────────────────────────────────────────

    def should_skip(self, text: str = "", caption: str = "") -> bool:
        """Return True if the message should be skipped based on skip terms."""
        if not self.skip_terms:
            return False
        blob = f"{text} {caption}".lower()
        for term in self.skip_terms:
            if term in blob:
                logger.debug(f"Skip term matched: '{term}'")
                return True
        return False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def resolve_chat_id(self, value: str):
        """Convert string chat ID to int if numeric, else return as-is (username)."""
        stripped = value.lstrip("-")
        return int(value) if stripped.isdigit() else value
