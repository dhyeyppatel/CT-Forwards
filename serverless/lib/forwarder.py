"""
forwarder.py — Pure utility functions shared by both forwarding modes.

No database or network calls here — all functions are stateless transforms.
"""
import re
import logging

logger = logging.getLogger(__name__)


# ── Rule parsing (used for first-run DB seeding) ──────────────────────────────

def parse_rules_raw(raw: str) -> list[dict]:
    """
    Parse the FORWARD_RULES env-var format into a list of rule dicts.

    Format: SOURCE:TARGET[,TARGET2];SOURCE2:TARGET3
    Returns: [{"sources": [...], "targets": [...]}, ...]
    """
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


# ── Chat ID helper ────────────────────────────────────────────────────────────

def resolve_chat_id(value: str):
    """Return int if the value is a numeric chat ID, otherwise return as-is (username)."""
    s = str(value).lstrip("-")
    return int(value) if s.isdigit() else value


# ── Text processing pipeline ──────────────────────────────────────────────────

def apply_text_processing(
    text: str,
    replacements: list[dict],
    prefix: str = "",
    suffix: str = "",
) -> str:
    """
    Apply word replacements then prefix/suffix to a text string.

    Args:
        text:         Original message text or caption.
        replacements: List of {"from_word": ..., "to_word": ...} dicts from DB.
        prefix:       Text to prepend (separated by newline).
        suffix:       Text to append (separated by newline).

    Returns:
        The modified text.  Returns the original text unchanged if nothing applies.
    """
    if text is None:
        text = ""

    # 1. Word replacements
    for r in replacements:
        text = text.replace(r["from_word"], r["to_word"])

    # 2. Prefix / suffix
    parts: list[str] = []
    if prefix:
        parts.append(prefix.strip())
    if text:
        parts.append(text)
    if suffix:
        parts.append(suffix.strip())

    return "\n".join(parts) if parts else text


# ── Skip check ────────────────────────────────────────────────────────────────

def should_skip(text: str, caption: str, skip_terms: list[dict]) -> bool:
    """
    Return True if the message should be skipped.

    Args:
        text:       Message text (may be empty).
        caption:    Media caption (may be empty).
        skip_terms: List of {"term": ...} dicts from DB.
    """
    if not skip_terms:
        return False
    blob = f"{text or ''} {caption or ''}".lower()
    for entry in skip_terms:
        term = entry["term"] if isinstance(entry, dict) else entry
        if term.lower() in blob:
            logger.debug(f"⏭️  Skip term matched: '{term}'")
            return True
    return False
