"""Text normalisation. The original text is always kept in raw_snapshots; this only produces the working copy."""

from __future__ import annotations

import html
import re
import unicodedata

_BLOCK_BREAK = re.compile(r"(?i)<\s*(?:br|/p|/div|/li|/h[1-6]|/tr|/ul|/ol)\s*/?>")
_LIST_ITEM = re.compile(r"(?i)<\s*li[^>]*>")
_TAG = re.compile(r"<[^>]+>")
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_SPACES = re.compile(r"[ \t     ]+")


def html_to_text(s: str) -> str:
    if "<" not in s or ">" not in s:
        return html.unescape(s)
    s = _BLOCK_BREAK.sub("\n", s)
    s = _LIST_ITEM.sub("\n• ", s)
    s = _TAG.sub(" ", s)
    return html.unescape(s)


def normalize_text(s: str | None) -> str:
    s = html_to_text(s or "")
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _ZERO_WIDTH.sub("", s)
    s = _SPACES.sub(" ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
