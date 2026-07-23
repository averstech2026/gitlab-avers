"""Attach Planka labels like pr:Front when a GitLab issue is linked to a code project (MR)."""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

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


def label_name_for_project(path_with_namespace: str, project_name: str = "") -> Optional[str]:
    path = (path_with_namespace or "").strip("/")
    if not path:
        return None
    low = path.lower()
    if low == "avers/avers":
        return None

    mapped = _label_map().get(low)
    if mapped:
        return mapped

    name = (project_name or path.split("/")[-1] or "").strip()
    if not name:
        return None
    return f"pr:{name}"


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
        name=label_name,
        color=DEFAULT_LABEL_COLOR,
    )
    await planka.add_card_label(card_id, str(label["id"]))
    log.info(
        "applied Planka label %r to card %s from gitlab project %s",
        label_name,
        card_id,
        project_path,
    )
    return label_name


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
