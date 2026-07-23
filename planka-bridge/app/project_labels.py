"""Attach Planka labels like git:Front from GitLab Issue labels or related MRs."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .clients import GitLabClient, PlankaClient
from .settings import settings
from .store import Store

log = logging.getLogger("bridge.project_labels")

# mentioned in merge request avers/front!12
# merge request avers/front!12
MR_PATH_RE = re.compile(
    r"(?:merge request|mentioned in merge request)\s+([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)!(\d+)",
    re.I,
)
# also plain path!iid
MR_PATH_SHORT_RE = re.compile(
    r"\b([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)!(\d+)\b",
)

DEFAULT_LABEL_COLOR = "berry-red"
LABEL_PREFIX = "git:"
# Planka API has no hard name limit; keep chips readable in the UI.
MAX_LABEL_NAME_LEN = 16

# One-click labels on AVERS Issue → Planka (no MR needed)
DEFAULT_ISSUE_LABEL_MAP: dict[str, str] = {
    "front": "git:Front",
    "plugins": "git:Plugins",
    "backend": "git:Backend",
    "взяли": "git:взяли",
    "in progress": "git:взяли",
    "in-progress": "git:взяли",
    "in_progress": "git:взяли",
}

# Never mirror these back to Planka
SKIP_GITLAB_ISSUE_LABELS = frozenset(
    {
        "from-planka",
    }
)


def _truncate_label_name(name: str) -> str:
    name = name.strip()
    if len(name) <= MAX_LABEL_NAME_LEN:
        return name
    # keep prefix intact when truncating
    if name.startswith(LABEL_PREFIX) and MAX_LABEL_NAME_LEN > len(LABEL_PREFIX) + 1:
        body_max = MAX_LABEL_NAME_LEN - len(LABEL_PREFIX) - 1  # room for …
        return f"{LABEL_PREFIX}{name[len(LABEL_PREFIX):][:body_max]}…"
    return name[: MAX_LABEL_NAME_LEN - 1] + "…"


def _label_map() -> dict[str, str]:
    """gitlab path_with_namespace (lower) → planka label name."""
    raw = (settings.gitlab_project_label_map or "").strip()
    out: dict[str, str] = {}
    if raw:
        try:
            data = json.loads(raw)
            out = {str(k).lower().strip("/"): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            log.warning("invalid GITLAB_PROJECT_LABEL_MAP JSON")
    return out


def _issue_label_map() -> dict[str, str]:
    """gitlab issue label title (lower) → planka label name."""
    out = dict(DEFAULT_ISSUE_LABEL_MAP)
    raw = (settings.gitlab_issue_label_map or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            for k, v in data.items():
                out[str(k).lower().strip()] = str(v)
        except json.JSONDecodeError:
            log.warning("invalid GITLAB_ISSUE_LABEL_MAP JSON")
    return out


def label_name_for_project(path_with_namespace: str, project_name: str = "") -> Optional[str]:
    path = (path_with_namespace or "").strip("/")
    if not path:
        return None
    # Numeric ids are not project paths — never create labels like git:3
    if path.isdigit():
        log.warning("skip label: path looks like numeric id %r", path)
        return None
    low = path.lower()
    if low == "avers/avers":
        return None

    mapped = _label_map().get(low)
    if mapped:
        return _truncate_label_name(mapped)

    name = (project_name or path.split("/")[-1] or "").strip()
    if not name or name.isdigit():
        return None
    return _truncate_label_name(f"{LABEL_PREFIX}{name}")


def planka_label_for_gitlab_issue_label(title: str) -> Optional[str]:
    """Map a GitLab Issue label title to a Planka label name, or None to skip."""
    t = (title or "").strip()
    if not t:
        return None
    low = t.lower()
    if low in SKIP_GITLAB_ISSUE_LABELS or low.startswith("planka:"):
        return None
    mapped = _issue_label_map().get(low)
    if mapped:
        return _truncate_label_name(mapped)
    # Pass through explicit git:* labels as-is
    if low.startswith("git:"):
        return _truncate_label_name(t)
    return None


def extract_issue_label_titles(payload: dict[str, Any]) -> list[str]:
    """Collect current label titles from a GitLab Issue webhook payload."""
    raw = payload.get("labels")
    if not isinstance(raw, list) or not raw:
        raw = (payload.get("object_attributes") or {}).get("labels") or []
    titles: list[str] = []
    for lab in raw:
        if isinstance(lab, dict):
            t = (lab.get("title") or lab.get("name") or "").strip()
        else:
            t = str(lab).strip()
        if t and t.lower() not in {x.lower() for x in titles}:
            titles.append(t)
    return titles


def extract_project_paths_from_note(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for rx in (MR_PATH_RE, MR_PATH_SHORT_RE):
        for m in rx.finditer(text):
            path = m.group(1)
            if path.lower() not in {p.lower() for p in found}:
                found.append(path)
    return found


async def apply_named_label_to_card(
    planka: PlankaClient,
    store: Store,
    *,
    card_id: str,
    label_name: str,
) -> Optional[str]:
    name = _truncate_label_name(label_name)
    if not name:
        return None

    link = store.get_by_card(card_id)
    board_id = (link or {}).get("board_id")
    if not board_id:
        card = await planka.get_card(card_id)
        board_id = str((card.get("item") or {}).get("boardId") or "")
    if not board_id:
        log.warning("no board_id for card %s", card_id)
        return None

    label = await planka.ensure_board_label(
        str(board_id),
        name=name,
        color=DEFAULT_LABEL_COLOR,
    )
    await planka.add_card_label(card_id, str(label["id"]))
    log.info("applied Planka label %r to card %s", name, card_id)
    return name


async def apply_project_label_to_card(
    planka: PlankaClient,
    store: Store,
    *,
    card_id: str,
    project_path: str,
    project_name: str = "",
) -> Optional[str]:
    label_name = label_name_for_project(project_path, project_name)
    if not label_name:
        log.info("skip label for project %s (queue or empty)", project_path)
        return None
    return await apply_named_label_to_card(
        planka, store, card_id=card_id, label_name=label_name
    )


async def sync_labels_from_gitlab_issue_labels(
    planka: PlankaClient,
    store: Store,
    *,
    card_id: str,
    gitlab_label_titles: list[str],
) -> list[str]:
    """Apply Planka labels from GitLab Issue label titles (one-click path)."""
    applied: list[str] = []
    for title in gitlab_label_titles:
        planka_name = planka_label_for_gitlab_issue_label(title)
        if not planka_name:
            continue
        name = await apply_named_label_to_card(
            planka, store, card_id=card_id, label_name=planka_name
        )
        if name and name not in applied:
            applied.append(name)
    return applied


async def sync_labels_from_related_mrs(
    planka: PlankaClient,
    gitlab: GitLabClient,
    store: Store,
    *,
    card_id: str,
    issue_iid: int,
) -> list[str]:
    mrs = await gitlab.list_related_merge_requests(int(issue_iid))
    applied: list[str] = []
    for mr in mrs:
        path = (
            mr.get("references", {}).get("full", "").split("!")[0]
            if isinstance(mr.get("references"), dict)
            else ""
        )
        # prefer project_id lookup
        proj = mr.get("web_url") or ""
        # web_url like https://git.../avers/front/-/merge_requests/1
        m = re.search(r"/([^/]+/[^/]+)/-/merge_requests/", proj)
        if m:
            path = m.group(1)
        name = ""
        # source_project_id
        spid = mr.get("source_project_id") or mr.get("project_id")
        if spid:
            try:
                p = await gitlab.get_project(str(spid))
                path = p.get("path_with_namespace") or path
                name = p.get("name") or ""
            except Exception:
                log.exception("project lookup failed for %s", spid)
        if not path:
            continue
        label = await apply_project_label_to_card(
            planka,
            store,
            card_id=card_id,
            project_path=path,
            project_name=name,
        )
        if label and label not in applied:
            applied.append(label)
    return applied
