"""Parse MFC daily paste lists (Intraservice/UCG URLs + short text titles).

help.ucg.ru — IntraService (проверено: IntraService 4.60, /api/task/{id}).
Ссылки вида /Task/View/{id} парсятся без API. Title/Description из SD —
только с Basic-auth (см. intraservice.py).
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

# Host can be overridden (default MFC UCG)
DEFAULT_HOST = os.getenv("INTRASERVICE_HOST", "help.ucg.ru").lower()

# Full URL anywhere in the line (chat often pastes bare URL or with trailing junk)
INTRASERVICE_URL_RE = re.compile(
    r"https?://(?P<host>[^\s/]+)/(?P<path>Task)/(?P<action>View|Edit)/(?P<id>\d+)"
    r"(?:[/?#][^\s]*)?",
    re.IGNORECASE,
)

# Bare path without scheme (редко копируют из UI)
INTRASERVICE_PATH_RE = re.compile(
    r"(?:^|\s)/(?:Task)/(?:View|Edit)/(\d+)(?:[/?#]\S*)?",
    re.IGNORECASE,
)


@dataclass
class ParsedRow:
    source_type: str  # url | text
    title: str
    external_url: str | None = None
    external_id: str | None = None
    object_hint: str | None = None
    typical_hint: str | None = None
    selected: bool = True
    # filled later via API enrich
    external_name: str | None = None
    external_description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_view_url(host: str, task_id: str) -> str:
    return f"https://{host}/Task/View/{task_id}"


def _allowed_host(host: str) -> bool:
    host = host.lower().split(":")[0]
    allowed = {
        DEFAULT_HOST,
        "help.ucg.ru",
    }
    extra = os.getenv("INTRASERVICE_EXTRA_HOSTS", "")
    for h in extra.split(","):
        h = h.strip().lower()
        if h:
            allowed.add(h)
    return host in allowed


def extract_intraservice_url(line: str) -> tuple[str, str] | None:
    """Return (task_id, canonical_url) if line contains an Intraservice task link."""
    m = INTRASERVICE_URL_RE.search(line)
    if m:
        host = m.group("host").lower()
        if not _allowed_host(host):
            return None
        eid = m.group("id")
        return eid, _canonical_view_url(host, eid)
    m2 = INTRASERVICE_PATH_RE.search(line)
    if m2 and _line_is_mostly_path(line):
        eid = m2.group(1)
        return eid, _canonical_view_url(DEFAULT_HOST, eid)
    return None


def _line_is_mostly_path(line: str) -> bool:
    """Avoid treating 'см. /Task/View/1 в письме' as pure URL row — only near-bare paths."""
    stripped = line.strip()
    return bool(re.fullmatch(r"/Task/(?:View|Edit)/\d+/?", stripped, re.I))


def _split_object_typical(text: str) -> tuple[str | None, str | None]:
    """`Prefix. Rest` → object_hint, typical_hint (first dot only)."""
    if "." not in text:
        return None, text.strip() or None
    left, right = text.split(".", 1)
    left, right = left.strip(), right.strip()
    if not left or not right:
        return None, text.strip() or None
    return left, right


def parse_list(raw: str) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip common chat wrappers: <url>, [url](url), surrounding <>
        cleaned = line.strip("<>").strip()
        md = re.fullmatch(r"\[([^\]]*)\]\((https?://[^)]+)\)", cleaned)
        if md:
            cleaned = md.group(2)

        found = extract_intraservice_url(cleaned)
        if found:
            eid, url = found
            # If line is ONLY the URL (maybe with whitespace junk after), treat as url row.
            # If URL is embedded in a longer sentence, still prefer url-row for MFC paste
            # when the line is mostly the link (no other words of substance).
            remainder = INTRASERVICE_URL_RE.sub("", cleaned).strip(" -–—|\t")
            if not remainder or len(remainder) < 3:
                rows.append(
                    ParsedRow(
                        source_type="url",
                        title=f"UCG #{eid}",
                        external_url=url,
                        external_id=eid,
                    )
                )
                continue
            # URL + text on same line: keep text as title, attach external link
            object_hint, typical_hint = _split_object_typical(remainder)
            rows.append(
                ParsedRow(
                    source_type="text",
                    title=remainder,
                    external_url=url,
                    external_id=eid,
                    object_hint=object_hint,
                    typical_hint=typical_hint,
                )
            )
            continue

        object_hint, typical_hint = _split_object_typical(line)
        rows.append(
            ParsedRow(
                source_type="text",
                title=line,
                object_hint=object_hint,
                typical_hint=typical_hint,
            )
        )
    return rows


def host_from_url(url: str) -> str:
    try:
        return urlparse(url).hostname or DEFAULT_HOST
    except Exception:
        return DEFAULT_HOST
