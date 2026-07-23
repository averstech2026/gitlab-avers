"""Markers and helpers for Planka ↔ GitLab comment sync (anti-loop)."""
from __future__ import annotations

import re

# Hidden markers — if present, the other side must not mirror again.
FROM_GITLAB = "<!-- bridge:from-gitlab -->"
FROM_PLANKA = "<!-- bridge:from-planka -->"

BRIDGE_MARKER_RE = re.compile(
    r"<!--\s*bridge:from-(?:gitlab|planka)\s*-->",
    re.I,
)

# Bridge-authored status lines — never mirror as user comments.
SYSTEM_PREFIXES = (
    "Создана задача в GitLab:",
    "Issue в GitLab переоткрыт:",
    "Issue в GitLab закрыт",
    "Issue в GitLab переоткрыт",
)


def is_bridged(text: str | None) -> bool:
    if not text:
        return False
    return bool(BRIDGE_MARKER_RE.search(text))


def is_system_bridge_message(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip()
    return any(t.startswith(p) for p in SYSTEM_PREFIXES)


def wrap_from_gitlab(author: str, body: str) -> str:
    author = (author or "GitLab").strip()
    body = (body or "").strip()
    return f"{FROM_GITLAB}\n**{author}** (GitLab):\n\n{body}"


def wrap_from_planka(author: str, body: str) -> str:
    author = (author or "Planka").strip()
    body = (body or "").strip()
    return f"{FROM_PLANKA}\n**{author}** (Planka):\n\n{body}"


def should_mirror_outbound(text: str | None) -> bool:
    """True if this user comment should be synced to the other system."""
    if not text or not text.strip():
        return False
    if is_bridged(text):
        return False
    if is_system_bridge_message(text):
        return False
    return True
