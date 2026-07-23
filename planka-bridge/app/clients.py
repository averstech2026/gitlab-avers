from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .settings import settings

log = logging.getLogger("bridge.planka")


class PlankaClient:
    def __init__(self) -> None:
        self.base = settings.planka_base_url.rstrip("/")
        self._token: str | None = None
        self._list_cache: dict[str, dict] = {}
        self._board_cache: dict[str, dict] = {}

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        r = await client.post(
            f"{self.base}/api/access-tokens",
            json={
                "emailOrUsername": settings.planka_email,
                "password": settings.planka_password,
            },
        )
        r.raise_for_status()
        self._token = r.json()["item"]
        return self._token

    async def _headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        token = await self._ensure_token(client)
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def get_card(self, card_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await self._headers(client)
            r = await client.get(f"{self.base}/api/cards/{card_id}", headers=headers)
            if r.status_code == 401:
                self._token = None
                headers = await self._headers(client)
                r = await client.get(f"{self.base}/api/cards/{card_id}", headers=headers)
            r.raise_for_status()
            return r.json()

    async def get_board(self, board_id: str) -> dict:
        if board_id in self._board_cache:
            return self._board_cache[board_id]
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await self._headers(client)
            r = await client.get(f"{self.base}/api/boards/{board_id}", headers=headers)
            if r.status_code == 401:
                self._token = None
                headers = await self._headers(client)
                r = await client.get(f"{self.base}/api/boards/{board_id}", headers=headers)
            r.raise_for_status()
            data = r.json()
            self._board_cache[board_id] = data
            for lst in (data.get("included") or {}).get("lists") or []:
                if lst.get("id"):
                    self._list_cache[str(lst["id"])] = lst
            return data

    async def get_list(self, list_id: str, board_id: str | None = None) -> dict | None:
        lid = str(list_id)
        if lid in self._list_cache:
            return self._list_cache[lid]
        if board_id:
            await self.get_board(str(board_id))
            return self._list_cache.get(lid)
        return None

    def invalidate_board(self, board_id: str) -> None:
        self._board_cache.pop(str(board_id), None)

    async def move_card(self, card_id: str, list_id: str, position: float = 65535) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await self._headers(client)
            r = await client.patch(
                f"{self.base}/api/cards/{card_id}",
                headers=headers,
                json={"listId": str(list_id), "position": position},
            )
            if r.status_code == 401:
                self._token = None
                headers = await self._headers(client)
                r = await client.patch(
                    f"{self.base}/api/cards/{card_id}",
                    headers=headers,
                    json={"listId": str(list_id), "position": position},
                )
            r.raise_for_status()
            return r.json()

    async def add_comment(self, card_id: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await self._headers(client)
            r = await client.post(
                f"{self.base}/api/cards/{card_id}/comments",
                headers=headers,
                json={"text": text},
            )
            if r.status_code == 401:
                self._token = None
                headers = await self._headers(client)
                r = await client.post(
                    f"{self.base}/api/cards/{card_id}/comments",
                    headers=headers,
                    json={"text": text},
                )
            # older/newer Planka may use different paths — soft-fail
            if r.status_code >= 400:
                log.warning("comment failed %s %s", r.status_code, r.text[:300])

    def card_url(self, card_id: str) -> str:
        return f"{settings.planka_link_base}/cards/{card_id}"

    async def resolve_context(self, card: dict) -> dict[str, Any]:
        """Return project/board/list names for a card item."""
        board_id = str(card.get("boardId") or "")
        list_id = str(card.get("listId") or "")
        board_data = await self.get_board(board_id) if board_id else {}
        board = board_data.get("item") or {}
        lists = (board_data.get("included") or {}).get("lists") or []
        lst = next((x for x in lists if str(x.get("id")) == list_id), None)
        project_name = None
        # project name via /api/projects
        project_id = board.get("projectId")
        if project_id:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = await self._headers(client)
                r = await client.get(f"{self.base}/api/projects/{project_id}", headers=headers)
                if r.status_code == 200:
                    project_name = (r.json().get("item") or {}).get("name")
        return {
            "project_name": project_name,
            "board_name": board.get("name"),
            "board_id": board_id,
            "list_name": (lst or {}).get("name"),
            "list_id": list_id,
            "lists": [x for x in lists if x.get("name")],
        }

    async def next_list_after(self, board_id: str, list_id: str) -> dict | None:
        self.invalidate_board(board_id)
        board_data = await self.get_board(board_id)
        lists = sorted(
            [x for x in ((board_data.get("included") or {}).get("lists") or []) if x.get("name")],
            key=lambda x: x.get("position") or 0,
        )
        for i, lst in enumerate(lists):
            if str(lst.get("id")) == str(list_id):
                if i + 1 < len(lists):
                    return lists[i + 1]
                return None
        # fallback: card may already have moved — find ready list and take next
        ready = settings.planka_ready_list_name
        for i, lst in enumerate(lists):
            if (lst.get("name") or "").strip() == ready:
                if i + 1 < len(lists):
                    return lists[i + 1]
        return None


class GitLabClient:
    def __init__(self) -> None:
        self.base = settings.gitlab_base_url.rstrip("/")
        self._project_id: str | None = settings.gitlab_project_id or None

    def _headers(self) -> dict[str, str]:
        return {
            "PRIVATE-TOKEN": settings.gitlab_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def resolve_project_id(self) -> str:
        if self._project_id:
            return str(self._project_id)
        path = settings.gitlab_project_path.strip("/")
        encoded = quote(path, safe="")
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.base}/api/v4/projects/{encoded}",
                headers=self._headers(),
            )
            r.raise_for_status()
            self._project_id = str(r.json()["id"])
            return self._project_id

    async def create_issue(
        self,
        *,
        title: str,
        description: str,
        labels: list[str] | None = None,
    ) -> dict:
        project_id = await self.resolve_project_id()
        payload: dict[str, Any] = {"title": title, "description": description}
        if labels:
            payload["labels"] = ",".join(labels)
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.base}/api/v4/projects/{project_id}/issues",
                headers=self._headers(),
                json=payload,
            )
            r.raise_for_status()
            return r.json()

    async def get_issue(self, issue_iid: int) -> dict:
        project_id = await self.resolve_project_id()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{self.base}/api/v4/projects/{project_id}/issues/{int(issue_iid)}",
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    async def reopen_issue(self, issue_iid: int) -> dict:
        project_id = await self.resolve_project_id()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.put(
                f"{self.base}/api/v4/projects/{project_id}/issues/{int(issue_iid)}",
                headers=self._headers(),
                json={"state_event": "reopen"},
            )
            r.raise_for_status()
            return r.json()

    async def create_note(self, issue_iid: int, body: str) -> dict:
        project_id = await self.resolve_project_id()
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.base}/api/v4/projects/{project_id}/issues/{int(issue_iid)}/notes",
                headers=self._headers(),
                json={"body": body},
            )
            r.raise_for_status()
            return r.json()
