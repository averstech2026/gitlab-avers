"""Optional IntraService (help.ucg.ru) client — Basic auth.

API: GET https://{host}/api/task/{id}
Docs: IntraService API (resource /api/task).
Without credentials enrichment is unavailable; URL parsing still works.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any, Optional

import httpx


class IntraserviceError(RuntimeError):
    pass


def credentials_configured() -> bool:
    return bool(
        os.getenv("INTRASERVICE_BASIC")
        or (
            os.getenv("INTRASERVICE_USER")
            and os.getenv("INTRASERVICE_PASSWORD")
        )
    )


def _auth_header() -> Optional[str]:
    basic = os.getenv("INTRASERVICE_BASIC", "").strip()
    if basic:
        if basic.lower().startswith("basic "):
            return basic
        return f"Basic {basic}"
    user = os.getenv("INTRASERVICE_USER", "").strip()
    password = os.getenv("INTRASERVICE_PASSWORD", "")
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {token}"
    return None


def re_sub_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def fetch_task(task_id: str, *, host: Optional[str] = None) -> dict[str, Any]:
    host = (host or os.getenv("INTRASERVICE_HOST", "help.ucg.ru")).strip()
    auth = _auth_header()
    if not auth:
        raise IntraserviceError("INTRASERVICE_USER/PASSWORD or INTRASERVICE_BASIC not set")
    url = f"https://{host}/api/task/{task_id}"
    with httpx.Client(timeout=20.0) as client:
        r = client.get(
            url,
            headers={
                "Authorization": auth,
                "Accept": "application/json",
            },
        )
    if r.status_code == 401:
        raise IntraserviceError("Intraservice unauthorized (check credentials)")
    if r.status_code >= 400:
        raise IntraserviceError(f"Intraservice HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    # Versions differ: {"Task": {...}} | {"Tasks":[...]} | bare object
    if isinstance(data, dict):
        if isinstance(data.get("Task"), dict):
            return data["Task"]
        if data.get("Tasks"):
            return data["Tasks"][0]
        if data.get("Id") is not None or data.get("Name") is not None:
            return data
    if isinstance(data, list) and data:
        return data[0]
    raise IntraserviceError("Unexpected Intraservice response shape")


def list_tasks(
    *,
    search: Optional[str] = None,
    page: int = 1,
    pagesize: int = 30,
    host: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Recent / searchable tasks visible to the API user."""
    host = (host or os.getenv("INTRASERVICE_HOST", "help.ucg.ru")).strip()
    auth = _auth_header()
    if not auth:
        raise IntraserviceError("INTRASERVICE_USER/PASSWORD or INTRASERVICE_BASIC not set")
    params: dict[str, Any] = {
        "page": page,
        "pagesize": min(max(pagesize, 1), 100),
        "fields": "Id,Name,Description,StatusId,CreatorCompanyName,ServiceName,Created",
        "sort": "Id desc",
    }
    if search and search.strip():
        params["search"] = search.strip()
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"https://{host}/api/task",
            headers={"Authorization": auth, "Accept": "application/json"},
            params=params,
        )
    if r.status_code == 401:
        raise IntraserviceError("Intraservice unauthorized (check credentials)")
    if r.status_code >= 400:
        raise IntraserviceError(f"Intraservice HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if isinstance(data, dict):
        tasks = data.get("Tasks") or []
    elif isinstance(data, list):
        tasks = data
    else:
        tasks = []
    out = []
    for t in tasks:
        tid = t.get("Id") or t.get("id")
        if tid is None:
            continue
        name = t.get("Name") or t.get("name") or f"UCG #{tid}"
        desc = re_sub_html(str(t.get("Description") or t.get("description") or ""))
        out.append(
            {
                "id": int(tid),
                "name": str(name)[:255],
                "description": desc[:2000],
                "status_id": t.get("StatusId"),
                "company": t.get("CreatorCompanyName") or "",
                "service": t.get("ServiceName") or "",
                "created": t.get("Created") or "",
                "url": f"https://{host}/Task/View/{tid}",
            }
        )
    return out


def enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return row dict with external_name / description from API."""
    eid = row.get("external_id")
    if not eid:
        return row
    host = None
    if row.get("external_url"):
        from parser import host_from_url

        host = host_from_url(row["external_url"])
    try:
        task = fetch_task(str(eid), host=host)
    except IntraserviceError as e:
        row["enrich_error"] = str(e)
        return row
    name = task.get("Name") or task.get("name")
    desc = task.get("Description") or task.get("description")
    if name:
        row["external_name"] = str(name)
        if not row.get("title") or str(row["title"]).startswith("UCG #"):
            row["title"] = str(name)[:255]
    if desc:
        text = re_sub_html(str(desc))
        row["external_description"] = text
        if not row.get("description"):
            row["description"] = text[:2000]
    return row
