"""Minimal Okdesk REST client for MFC fast-create."""

from __future__ import annotations

import time
from typing import Any

import httpx


class OkdeskError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class OkdeskClient:
    def __init__(self, domain: str, token: str, *, timeout: float = 30.0):
        base = domain.rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        self.base = base
        self.token = token
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def _params(self, extra: dict | None = None) -> dict:
        p = {"api_token": self.token}
        if extra:
            p.update(extra)
        return p

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | list[tuple[str, Any]] | None = None,
        json_body: Any = None,
    ) -> Any:
        if isinstance(params, list):
            merged: list[tuple[str, Any]] = [("api_token", self.token), *params]
            req_params: Any = merged
        else:
            req_params = self._params(params)
        r = self._client.request(
            method,
            self._url(path),
            params=req_params,
            json=json_body,
        )
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise OkdeskError(
                f"Okdesk {method} {path} → {r.status_code}",
                status=r.status_code,
                body=body,
            )
        if not r.content:
            return None
        return r.json()

    def search_maintenance_entities(self, q: str) -> list[dict]:
        data = self.request(
            "GET",
            "/api/v1/maintenance_entities/",
            params={"search_string": q},
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("maintenance_entities") or data.get("items") or []
        return []

    def list_maintenance_entities_for_company(
        self, company_id: int, *, page_size: int = 100
    ) -> list[dict]:
        """Paginate maintenance_entities/list filtered by company."""
        items: list[dict] = []
        from_id: int | None = None
        while True:
            params: list[tuple[str, Any]] = [
                ("company_ids[]", company_id),
                ("page[size]", page_size),
                ("page[direction]", "forward"),
            ]
            if from_id is not None:
                params.append(("page[from_id]", from_id))
            batch = self.request(
                "GET", "/api/v1/maintenance_entities/list", params=params
            )
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if len(batch) < page_size:
                break
            last_id = batch[-1].get("id")
            if last_id is None or last_id == from_id:
                break
            from_id = int(last_id)
            time.sleep(0.05)
        return items

    def search_companies(self, q: str = "", *, limit: int = 40) -> list[dict]:
        """Search companies; empty q → first page of /companies/list."""
        q = (q or "").strip()
        if q:
            data = self.request(
                "GET",
                "/api/v1/companies/",
                params={"search_string": q},
            )
        else:
            data = self.request(
                "GET",
                "/api/v1/companies/list",
                params=[
                    ("page[size]", min(limit, 100)),
                    ("page[direction]", "forward"),
                ],
            )
        if isinstance(data, list):
            return data[:limit]
        if isinstance(data, dict):
            items = data.get("companies") or data.get("items") or []
            return items[:limit] if isinstance(items, list) else []
        return []

    def get_company(self, company_id: int) -> dict | None:
        data = self.request("GET", f"/api/v1/companies/{company_id}")
        return data if isinstance(data, dict) else None

    def list_employees(self, *, page_size: int = 100, max_pages: int = 50) -> list[dict]:
        """Paginate /employees/list (active+inactive; filter locally)."""
        items: list[dict] = []
        for page in range(1, max_pages + 1):
            try:
                batch = self.request(
                    "GET",
                    "/api/v1/employees/list",
                    params={
                        "page[number]": page,
                        "page[size]": page_size,
                    },
                )
            except OkdeskError:
                # fallback: some аккаунты отдают только /employees/
                if page == 1:
                    try:
                        batch = self.request(
                            "GET",
                            "/api/v1/employees/",
                            params={"page[size]": page_size},
                        )
                    except OkdeskError:
                        return items
                else:
                    break
            if isinstance(batch, dict):
                batch = (
                    batch.get("employees")
                    or batch.get("items")
                    or batch.get("users")
                    or []
                )
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if len(batch) < page_size:
                break
            time.sleep(0.05)
        return items

    def search_employees(self, q: str = "", *, limit: int = 40) -> list[dict]:
        """Best-effort employee search (endpoint availability varies by plan)."""
        q = (q or "").strip()
        params: dict[str, Any] = {"page[size]": min(limit, 100)}
        if q:
            params["search_string"] = q
        for path in ("/api/v1/employees/", "/api/v1/employees/list"):
            try:
                data = self.request("GET", path, params=params)
            except OkdeskError:
                continue
            if isinstance(data, list):
                return data[:limit]
            if isinstance(data, dict):
                items = (
                    data.get("employees")
                    or data.get("items")
                    or data.get("users")
                    or []
                )
                if isinstance(items, list):
                    return items[:limit]
        return []

    def create_issue(self, issue: dict) -> dict:
        data = self.request("POST", "/api/v1/issues/", json_body={"issue": issue})
        if isinstance(data, dict):
            return data
        raise OkdeskError("Unexpected create_issue response", body=data)

    def change_status(
        self,
        issue_id: int,
        code: str,
        *,
        comment: str | None = None,
        comment_public: bool = False,
        custom_parameters: dict | None = None,
    ) -> Any:
        body: dict[str, Any] = {"code": code}
        if comment is not None:
            body["comment"] = comment
            body["comment_public"] = comment_public
        if custom_parameters:
            body["custom_parameters"] = custom_parameters
        return self.request(
            "POST",
            f"/api/v1/issues/{issue_id}/statuses",
            json_body=body,
        )
