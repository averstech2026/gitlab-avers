"""Lightweight fuzzy helpers for object / typical hints."""

from __future__ import annotations

import re
import unicodedata


def normalize(s: str) -> str:
    s = (s or "").casefold()
    s = s.replace("\\", "/")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("ё", "е")
    s = re.sub(r"[\s_\-–—]+", " ", s)
    s = re.sub(r"[^\w\s/]+", "", s, flags=re.UNICODE)
    return s.strip()


def compact(s: str) -> str:
    """ПП 12 → пп12 — для кодов точек без пробелов."""
    return re.sub(r"\s+", "", normalize(s))


def _meaningful_prefix(a: str, b: str) -> bool:
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    # слишком короткие префиксы («пп», «12») дают ложные пп63↔ПП …
    if len(shorter) < 3:
        return False
    return longer.startswith(shorter)


def score_match(query: str, candidate: str) -> float:
    q = normalize(query)
    c = normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    qc = compact(query)
    cc = compact(candidate)
    if qc and cc:
        if qc == cc:
            return 1.0
        # полный код точки внутри имени объекта
        if len(qc) >= 3 and qc in cc:
            return 0.9
        if len(cc) >= 3 and cc in qc:
            return 0.85

    if q in c and len(q) >= 3:
        return 0.85
    if c in q and len(c) >= 3:
        return 0.85

    q_tokens = set(q.split())
    c_tokens = set(c.split())
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens) / len(q_tokens)
    if overlap >= 0.5:
        return 0.5 + 0.4 * overlap

    qt = next(iter(q_tokens))
    for ct in c_tokens:
        if _meaningful_prefix(qt, ct):
            return 0.55
    # compact token vs compact candidate pieces
    if qc and len(qc) >= 4:
        for ct in c_tokens:
            ctc = compact(ct)
            if ctc and _meaningful_prefix(qc, ctc):
                return 0.55
    return 0.0


def best_matches(
    query: str,
    candidates: list[dict],
    *,
    name_key: str = "name",
    limit: int = 8,
    min_score: float = 0.4,
) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for item in candidates:
        name = str(item.get(name_key) or "")
        sc = score_match(query, name)
        if sc >= min_score:
            scored.append((sc, item))
    scored.sort(key=lambda x: (-x[0], str(x[1].get(name_key) or "")))
    return [item for _, item in scored[:limit]]


def suggest_typical(hint: str, typicals: list[str], aliases: dict[str, str]) -> str | None:
    if not hint:
        return None
    h = normalize(hint)
    for key in sorted(aliases.keys(), key=len, reverse=True):
        if normalize(key) in h or h in normalize(key):
            return aliases[key]
    best: tuple[float, str] | None = None
    for t in typicals:
        sc = score_match(hint, t)
        if best is None or sc > best[0]:
            best = (sc, t)
    if best and best[0] >= 0.45:
        return best[1]
    return None
