"""
Normalization & tokenization helpers.

WHAT:
  - lowercasing, whitespace collapse, strip URLs/mentions, gentle punctuation,
    token list + join helpers used in scoring.

WHY:
  - Reduces false negatives; keeps model code clean and testable.
"""

import re
URL_RE = re.compile(r"https?://\S+")
MENTION_RE = re.compile(r"@\w+|<@!?[\d]+>")
PUNCT_RE = re.compile(r"[\-_/\\.,;:!?*^~`'\[\](){}<>]+")
WS_RE = re.compile(r"\s+")
def normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = URL_RE.sub(" ", t)
    t = MENTION_RE.sub(" ", t)
    t = PUNCT_RE.sub(" ", t)
    t = WS_RE.sub(" ", t).strip()
    return t
