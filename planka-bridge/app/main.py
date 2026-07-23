from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .clients import GitLabClient, PlankaClient
from .settings import settings
from .store import Store

log = logging.getLogger("bridge")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Planka ↔ GitLab bridge", version="1.0.0")
store = Store(settings.database_path)
planka = PlankaClient()
gitlab = GitLabClient()

CARD_MARKER_RE = re.compile(r"planka-card:(\d+)", re.I)


def _bearer_ok(authorization: Optional[str], expected: str) -> bool:
    if not expected:
        return True
    if not authorization:
        return False
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() == expected
    return authorization.strip() == expected


def _extract_card(data: Optional[dict]) -> Optional[dict]:
    if not data:
        return None
    item = data.get("item")
    if isinstance(item, dict) and item.get("id") and (
        "listId" in item or "boardId" in item or "name" in item
    ):
        return item
    cards = (data.get("included") or {}).get("cards") or []
    if cards:
        return cards[0]
    return item if isinstance(item, dict) else None


def _is_issue_close(attrs: dict) -> bool:
    action = (attrs.get("action") or "").lower()
    state = (attrs.get("state") or "").lower()
    if action in ("close", "closed"):
        return True
    if state == "closed" and action in ("update", "close", "closed", ""):
        return True
    return False


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/hooks/planka")
async def planka_hook(
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    if not _bearer_ok(authorization, settings.planka_webhook_token):
        raise HTTPException(status_code=401, detail="bad token")

    payload: dict[str, Any] = await request.json()
    event = payload.get("event")
    log.info("planka event=%s", event)

    if event != "cardUpdate":
        return {"ignored": True, "reason": "event"}

    card = _extract_card(payload.get("data"))
    prev = _extract_card(payload.get("prevData"))
    if not card:
        return {"ignored": True, "reason": "no-card"}

    new_list = str(card.get("listId") or "")
    old_list = str((prev or {}).get("listId") or "")
    if not new_list or new_list == old_list:
        return {"ignored": True, "reason": "list-unchanged"}

    board_id = str(card.get("boardId") or (prev or {}).get("boardId") or "")
    lst = await planka.get_list(new_list, board_id or None)
    if not lst and board_id:
        planka.invalidate_board(board_id)
        lst = await planka.get_list(new_list, board_id)
    list_name = (lst or {}).get("name") or ""
    if list_name.strip() != settings.planka_ready_list_name.strip():
        return {"ignored": True, "reason": "not-ready-list", "list": list_name}

    card_id = str(card.get("id"))
    existing = store.get_by_card(card_id)
    if existing:
        issue_iid = int(existing["issue_iid"])
        issue_url = existing.get("issue_url") or (
            f"{settings.gitlab_base_url.rstrip('/')}/"
            f"{settings.gitlab_project_path}/-/issues/{issue_iid}"
        )
        try:
            issue = await gitlab.get_issue(issue_iid)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.warning(
                    "card %s linked to missing issue !%s — creating new",
                    card_id,
                    issue_iid,
                )
            else:
                raise
        else:
            state = (issue.get("state") or "").lower()
            if state == "closed":
                reopened = await gitlab.reopen_issue(issue_iid)
                issue_url = reopened.get("web_url") or issue_url
                await planka.add_comment(
                    card_id,
                    f"Issue в GitLab переоткрыт: {issue_url}",
                )
                log.info("reopened gitlab issue !%s for card %s", issue_iid, card_id)
                return {
                    "ok": True,
                    "reopened": True,
                    "issue_iid": issue_iid,
                    "issue_url": issue_url,
                }
            log.info(
                "card %s already linked to open issue !%s",
                card_id,
                issue_iid,
            )
            return {
                "ok": True,
                "dedup": True,
                "issue_iid": issue_iid,
                "issue_url": issue_url,
            }

    full = await planka.get_card(card_id)
    card_item = full.get("item") or card
    ctx = await planka.resolve_context(card_item)

    title = (card_item.get("name") or f"Planka card {card_id}").strip()
    desc_parts = [
        (card_item.get("description") or "").strip(),
        "",
        "---",
        f"**Planka:** {planka.card_url(card_id)}",
        f"**Проект Planka:** {ctx.get('project_name') or '—'}",
        f"**Доска:** {ctx.get('board_name') or '—'}",
        f"<!-- planka-card:{card_id} -->",
    ]
    description = "\n".join(desc_parts).strip()
    labels = ["from-planka"]
    if ctx.get("project_name"):
        labels.append(f"planka:{ctx['project_name']}")

    issue = await gitlab.create_issue(title=title, description=description, labels=labels)
    issue_iid = issue["iid"]
    issue_url = issue.get("web_url") or (
        f"{settings.gitlab_base_url.rstrip('/')}/"
        f"{settings.gitlab_project_path}/-/issues/{issue_iid}"
    )

    store.upsert(
        card_id=card_id,
        issue_iid=issue_iid,
        issue_id=issue.get("id"),
        issue_url=issue_url,
        list_id=new_list,
        board_id=board_id or ctx.get("board_id"),
        project_name=ctx.get("project_name"),
        board_name=ctx.get("board_name"),
    )

    await planka.add_comment(card_id, f"Создана задача в GitLab: {issue_url}")
    log.info("created gitlab issue !%s for card %s", issue_iid, card_id)
    return {"ok": True, "issue_iid": issue_iid, "issue_url": issue_url}


@app.post("/hooks/gitlab")
async def gitlab_hook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(default=None),
    x_gitlab_event: Optional[str] = Header(default=None),
):
    if settings.gitlab_webhook_token and x_gitlab_token != settings.gitlab_webhook_token:
        raise HTTPException(status_code=401, detail="bad token")

    payload: dict[str, Any] = await request.json()
    object_kind = (payload.get("object_kind") or "").lower()
    event_header = (x_gitlab_event or "").lower()
    log.info("gitlab event_header=%s object_kind=%s", event_header, object_kind)

    if object_kind != "issue" and "issue" not in event_header:
        return {"ignored": True, "reason": "not-issue"}

    attrs = payload.get("object_attributes") or {}
    if not _is_issue_close(attrs):
        return {
            "ignored": True,
            "reason": "not-close",
            "action": attrs.get("action"),
            "state": attrs.get("state"),
        }

    issue_iid = attrs.get("iid")
    if not issue_iid:
        return {"ignored": True, "reason": "no-iid"}

    link = store.get_by_issue_iid(int(issue_iid))
    card_id = link["card_id"] if link else None
    if not card_id:
        m = CARD_MARKER_RE.search(attrs.get("description") or "")
        if m:
            card_id = m.group(1)

    if not card_id:
        log.info("no planka link for issue !%s", issue_iid)
        return {"ignored": True, "reason": "no-link"}

    full = await planka.get_card(card_id)
    card_item = full.get("item") or {}
    board_id = str(card_item.get("boardId") or (link or {}).get("board_id") or "")
    current_list_id = str(card_item.get("listId") or "")
    if not board_id:
        raise HTTPException(status_code=500, detail="card has no boardId")

    # Двигаем только если карточка ещё в колонке-триггере.
    # Если уже унесли вручную (Тестируется и т.п.) — не трогаем, чтобы не перепрыгнуть.
    board_data = await planka.get_board(board_id)
    lists = sorted(
        [
            x
            for x in ((board_data.get("included") or {}).get("lists") or [])
            if x.get("name")
        ],
        key=lambda x: x.get("position") or 0,
    )
    ready_name = settings.planka_ready_list_name.strip()
    ready = next(
        (x for x in lists if (x.get("name") or "").strip() == ready_name),
        None,
    )
    if not ready:
        return {"ok": False, "reason": "no-ready-list", "card_id": card_id}

    current = next((x for x in lists if str(x.get("id")) == current_list_id), None)
    current_name = (current or {}).get("name") or ""

    if str(current_list_id) != str(ready["id"]):
        log.info(
            "skip move card %s on issue !%s close: already in %r (not %r)",
            card_id,
            issue_iid,
            current_name,
            ready_name,
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "card-already-moved",
            "card_id": card_id,
            "list": current_name,
        }

    nxt = await planka.next_list_after(board_id, str(ready["id"]))
    if not nxt:
        return {"ok": False, "reason": "no-next-list", "card_id": card_id}

    await planka.move_card(card_id, str(nxt["id"]))
    await planka.add_comment(
        card_id,
        f"Issue в GitLab закрыт (!{issue_iid}) → колонка «{nxt.get('name')}»",
    )
    log.info(
        "moved card %s → %s after issue !%s closed",
        card_id,
        nxt.get("name"),
        issue_iid,
    )
    return {"ok": True, "card_id": card_id, "list": nxt.get("name")}


@app.exception_handler(httpx.HTTPStatusError)
async def httpx_error(request: Request, exc: httpx.HTTPStatusError):
    log.exception("upstream error")
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "body": exc.response.text[:500]},
    )
