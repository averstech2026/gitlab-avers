"""Map Planka card members → GitLab assignee user ids (by email / username / override)."""
from __future__ import annotations

import json
import logging
import time

from .clients import GitLabClient, PlankaClient
from .settings import settings

log = logging.getLogger("bridge.assignees")

_gitlab_users_cache: list[dict] | None = None
_gitlab_users_cached_at = 0.0
_CACHE_TTL = 300.0


def _overrides() -> dict[str, str]:
    """PLANKA_GITLAB_USER_MAP JSON: planka username/email → gitlab username."""
    raw = (settings.planka_gitlab_user_map or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k).lower(): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        log.warning("invalid PLANKA_GITLAB_USER_MAP JSON")
        return {}


async def _gitlab_users(gitlab: GitLabClient) -> list[dict]:
    global _gitlab_users_cache, _gitlab_users_cached_at
    now = time.time()
    if _gitlab_users_cache is not None and now - _gitlab_users_cached_at < _CACHE_TTL:
        return _gitlab_users_cache
    users = await gitlab.list_users()
    _gitlab_users_cache = users
    _gitlab_users_cached_at = now
    return users


def _match_gitlab_user(planka_user: dict, gitlab_users: list[dict], overrides: dict[str, str]) -> dict | None:
    email = (planka_user.get("email") or "").strip().lower()
    username = (planka_user.get("username") or "").strip().lower()
    name = (planka_user.get("name") or "").strip().lower()

    override_key = None
    for key in (username, email, name):
        if key and key in overrides:
            override_key = overrides[key]
            break
    if override_key:
        target = override_key.lower()
        for gu in gitlab_users:
            if (gu.get("username") or "").lower() == target:
                return gu
            if (gu.get("email") or "").lower() == target:
                return gu

    if email:
        for gu in gitlab_users:
            if (gu.get("email") or "").lower() == email:
                return gu

    if username:
        for gu in gitlab_users:
            if (gu.get("username") or "").lower() == username:
                return gu

    if name:
        for gu in gitlab_users:
            if (gu.get("name") or "").strip().lower() == name:
                return gu

    return None


async def gitlab_assignee_ids_for_card(
    planka: PlankaClient,
    gitlab: GitLabClient,
    card_id: str,
) -> list[int]:
    members = await planka.get_card_member_users(card_id)
    if not members:
        return []

    gitlab_users = await _gitlab_users(gitlab)
    overrides = _overrides()
    ids: list[int] = []
    seen: set[int] = set()

    for pu in members:
        gu = _match_gitlab_user(pu, gitlab_users, overrides)
        if not gu:
            log.warning(
                "no GitLab user for Planka assignee %r <%s> (@%s)",
                pu.get("name"),
                pu.get("email"),
                pu.get("username"),
            )
            continue
        uid = gu.get("id")
        if uid is None:
            continue
        uid = int(uid)
        if uid in seen:
            continue
        seen.add(uid)
        ids.append(uid)
        log.info(
            "mapped Planka @%s → GitLab @%s (id=%s)",
            pu.get("username"),
            gu.get("username"),
            uid,
        )
    return ids


async def sync_issue_assignees_from_card(
    planka: PlankaClient,
    gitlab: GitLabClient,
    *,
    card_id: str,
    issue_iid: int,
) -> list[int]:
    ids = await gitlab_assignee_ids_for_card(planka, gitlab, card_id)
    await gitlab.set_issue_assignees(issue_iid, ids)
    return ids
