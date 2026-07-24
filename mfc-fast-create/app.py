"""MFC fast-create: FastAPI proxy + static UI."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fuzzy import best_matches, suggest_typical
from intraservice import credentials_configured, enrich_row, list_tasks, IntraserviceError
from okdesk import OkdeskClient, OkdeskError
from parser import parse_list

ROOT = Path(__file__).resolve().parent
# In Docker image ROOT is /app — no repo parents
REPO_ROOT = ROOT.parents[1] if len(ROOT.parents) > 1 else ROOT

# Prefer tool-local .env, then repo root
load_dotenv(ROOT / ".env")
load_dotenv(REPO_ROOT / ".env")

CATALOGS = json.loads((ROOT / "catalogs.json").read_text(encoding="utf-8"))
COMPANY_ID = int(os.getenv("MFC_COMPANY_ID", CATALOGS.get("company_id", 9)))
ASSIGNEE_ID = int(os.getenv("MFC_ASSIGNEE_ID", CATALOGS.get("assignee_id", 5)))
# Группа «инженеры» / Support в Okdesk (как в ShiftPlanner assigneeGroupId)
ENGINEER_GROUP_ID = int(
    os.getenv("MFC_ENGINEER_GROUP_ID", CATALOGS.get("engineer_group_id", 7))
)
ISSUE_TYPE = os.getenv("MFC_ISSUE_TYPE", CATALOGS.get("issue_type", "service"))
# Comma-separated status codes applied in order after create (comment on first)
STATUS_CODES = [
    s.strip()
    for s in os.getenv("MFC_STATUS_CODES", "completed").split(",")
    if s.strip()
]
DRY_RUN_DEFAULT = os.getenv("MFC_DRY_RUN", "").lower() in ("1", "true", "yes")

app = FastAPI(title="MFC Fast Create", version="0.1.0")

# ShiftPlanner UI на GitHub Pages ходит сюда кросс-доменом
_cors = [
    o.strip()
    for o in os.getenv(
        "MFC_CORS_ORIGINS",
        "https://averstech2026.github.io,http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8787,http://localhost:8787",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

_objects_lock = threading.Lock()
_objects_cache_by_company: dict[int, tuple[float, list[dict]]] = {}
OBJECTS_TTL_SEC = 300.0


def _require_client() -> OkdeskClient:
    domain = os.getenv("OKDESK_DOMAIN", "").strip()
    token = os.getenv("OKDESK_API_TOKEN", "").strip()
    if not domain or not token:
        raise HTTPException(
            status_code=500,
            detail="OKDESK_DOMAIN / OKDESK_API_TOKEN not configured",
        )
    return OkdeskClient(domain, token)


def _normalize_object(raw: dict) -> dict:
    company = raw.get("company") or {}
    cid = company.get("id") if isinstance(company, dict) else raw.get("company_id")
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "company_id": cid,
        "comment": raw.get("comment") or "",
    }


def _normalize_company(raw: dict) -> dict | None:
    cid = raw.get("id")
    if cid is None:
        return None
    name = raw.get("name") or raw.get("additional_name") or f"Компания #{cid}"
    return {"id": int(cid), "name": str(name)}


def _normalize_employee(raw: dict) -> dict | None:
    eid = raw.get("id")
    if eid is None:
        return None
    name = (
        raw.get("name")
        or raw.get("full_name")
        or " ".join(
            p
            for p in [
                raw.get("last_name") or "",
                raw.get("first_name") or "",
                raw.get("patronymic") or "",
            ]
            if p
        ).strip()
        or f"Сотрудник #{eid}"
    )
    active = raw.get("active")
    if active is None:
        active = raw.get("is_active")
    group_ids: list[int] = []
    for g in raw.get("groups") or []:
        if isinstance(g, dict) and g.get("id") is not None:
            group_ids.append(int(g["id"]))
    for key in ("default_assignee_group", "group"):
        g = raw.get(key)
        if isinstance(g, dict) and g.get("id") is not None:
            group_ids.append(int(g["id"]))
    return {
        "id": int(eid),
        "name": str(name),
        "active": False if active is False else True,
        "group_ids": sorted(set(group_ids)),
    }


def _employee_in_engineer_group(emp: dict, group_id: int) -> bool:
    if not emp or emp.get("active") is False:
        return False
    gid = int(group_id)
    return any(int(x) == gid for x in (emp.get("group_ids") or []))


def _catalog_companies() -> list[dict]:
    items = list(CATALOGS.get("companies") or [])
    default = {
        "id": COMPANY_ID,
        "name": CATALOGS.get("company_name") or f"Компания #{COMPANY_ID}",
    }
    if not any(int(x.get("id", -1)) == COMPANY_ID for x in items):
        items = [default, *items]
    return [{"id": int(x["id"]), "name": str(x.get("name") or x["id"])} for x in items]


def _catalog_employees() -> list[dict]:
    """Локальный пресет — только дефолтный ответственный (полный список из Okdesk)."""
    return [
        {
            "id": ASSIGNEE_ID,
            "name": CATALOGS.get("assignee_name") or f"Сотрудник #{ASSIGNEE_ID}",
            "active": True,
            "group_ids": [ENGINEER_GROUP_ID],
        }
    ]


def _merge_named(primary: list[dict], extra: list[dict]) -> list[dict]:
    by_id: dict[int, dict] = {}
    for item in [*primary, *extra]:
        try:
            iid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        by_id[iid] = {
            "id": iid,
            "name": str(item.get("name") or iid),
            "active": item.get("active", True),
            "group_ids": list(item.get("group_ids") or []),
        }
    return sorted(by_id.values(), key=lambda x: str(x["name"]).casefold())


_employees_lock = threading.Lock()
_employees_cache: tuple[float, list[dict]] | None = None
EMPLOYEES_TTL_SEC = 300.0


def _load_engineer_employees(force: bool = False) -> list[dict]:
    """Активные сотрудники группы инженеров (Support)."""
    global _employees_cache
    now = time.time()
    with _employees_lock:
        if (
            not force
            and _employees_cache
            and now - _employees_cache[0] < EMPLOYEES_TTL_SEC
        ):
            return list(_employees_cache[1])

    remote: list[dict] = []
    try:
        client = _require_client()
        try:
            for raw in client.list_employees():
                item = _normalize_employee(raw if isinstance(raw, dict) else {})
                if item and _employee_in_engineer_group(item, ENGINEER_GROUP_ID):
                    remote.append(item)
        finally:
            client.close()
    except HTTPException:
        remote = []
    except Exception:
        remote = []

    # если API пуст — хотя бы дефолтный Артём из каталога
    items = _merge_named(_catalog_employees() if not remote else [], remote)
    items = [
        {"id": x["id"], "name": x["name"]}
        for x in items
        if x.get("active") is not False
    ]
    with _employees_lock:
        _employees_cache = (time.time(), items)
        return list(items)


def _load_objects(company_id: int, force: bool = False) -> list[dict]:
    now = time.time()
    with _objects_lock:
        cached = _objects_cache_by_company.get(int(company_id))
        if (
            not force
            and cached
            and now - cached[0] < OBJECTS_TTL_SEC
        ):
            return cached[1]
    client = _require_client()
    try:
        raw = client.list_maintenance_entities_for_company(int(company_id))
    except OkdeskError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        client.close()
    items = [_normalize_object(x) for x in raw]
    items = [x for x in items if x.get("id") is not None]
    with _objects_lock:
        _objects_cache_by_company[int(company_id)] = (time.time(), items)
        return items


def _cached_objects(company_id: int) -> list[dict]:
    with _objects_lock:
        cached = _objects_cache_by_company.get(int(company_id))
        return list(cached[1]) if cached else []


def _build_close_comment(solution: str, batch_comment: str | None, external_url: str | None) -> str:
    parts = ["Техническое решение.", f"Способ: {solution}"]
    if external_url:
        parts.append(f"UCG: {external_url}")
    if batch_comment and batch_comment.strip():
        parts.append(batch_comment.strip())
    return "\n".join(parts)


class ParseRequest(BaseModel):
    text: str = ""
    enrich: bool = False
    company_id: Optional[int] = None


class BatchItem(BaseModel):
    title: str
    object_id: int
    typical: str
    solution: str
    selected: bool = True
    external_url: Optional[str] = None
    description: Optional[str] = None
    # docs/21: complication_level + complication (оба или ни одного), object_count
    complication_level: Optional[str] = None
    complication: Optional[str] = None
    object_count: Optional[str] = None


class BatchRequest(BaseModel):
    items: list[BatchItem]
    batch_comment: Optional[str] = None
    dry_run: Optional[bool] = None
    company_id: Optional[int] = None
    assignee_id: Optional[int] = None


def _build_custom_parameters(item: BatchItem) -> dict[str, Any]:
    params: dict[str, Any] = {
        "typical": item.typical,
        "solution_method": [item.solution],
    }
    level = (item.complication_level or "").strip()
    text = (item.complication or "").strip()
    if level:
        params["complication_level"] = level
    if text:
        params["complication"] = text
    n = (item.object_count or "").strip()
    if n:
        params["object_count"] = n
    return params


def _validate_extra_fields(item: BatchItem) -> Optional[str]:
    level = (item.complication_level or "").strip()
    text = (item.complication or "").strip()
    allowed = set(CATALOGS.get("complication_levels") or ["+15", "+30"])
    if level and level not in allowed:
        return f"complication_level must be one of {sorted(allowed)}"
    if level and not text:
        return "при осложнении нужно «Описание осложнения» (complication)"
    if text and not level:
        return "есть описание осложнения без уровня (+15/+30)"
    n = (item.object_count or "").strip()
    if n and not n.isdigit():
        return "object_count должен быть целым числом (строка цифр)"
    if n and int(n) < 1:
        return "object_count должен быть ≥ 1"
    return None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/mfc/health")
def health() -> dict[str, Any]:
    """Статусы интеграций для бейджа в шапке."""
    okdesk: dict[str, Any]
    intraservice: dict[str, Any]
    domain = os.getenv("OKDESK_DOMAIN", "").strip()
    token = os.getenv("OKDESK_API_TOKEN", "").strip()
    if not domain or not token:
        okdesk = {"status": "offline", "detail": "нет OKDESK_DOMAIN / TOKEN"}
    else:
        try:
            client = OkdeskClient(domain, token, timeout=12.0)
            client.search_maintenance_entities("МФС")
            client.close()
            okdesk = {"status": "connected", "detail": domain.rstrip("/")}
        except Exception as e:
            okdesk = {"status": "error", "detail": str(e)[:120]}

    if not credentials_configured():
        intraservice = {
            "status": "offline",
            "detail": "нет INTRASERVICE_USER/PASSWORD",
        }
    else:
        try:
            items = list_tasks(pagesize=1)
            intraservice = {
                "status": "connected",
                "detail": os.getenv("INTRASERVICE_HOST", "help.ucg.ru"),
                "sample": items[0]["id"] if items else None,
            }
        except IntraserviceError as e:
            intraservice = {"status": "error", "detail": str(e)[:120]}
        except Exception as e:
            intraservice = {"status": "error", "detail": str(e)[:120]}

    return {"okdesk": okdesk, "intraservice": intraservice}


@app.get("/api/mfc/catalogs")
def catalogs() -> dict[str, Any]:
    domain = os.getenv("OKDESK_DOMAIN", "https://avers.okdesk.ru").rstrip("/")
    engineers = _load_engineer_employees()
    return {
        "company_id": COMPANY_ID,
        "assignee_id": ASSIGNEE_ID,
        "company_name": CATALOGS.get("company_name")
        or f"Компания #{COMPANY_ID}",
        "assignee_name": CATALOGS.get("assignee_name")
        or f"Сотрудник #{ASSIGNEE_ID}",
        "engineer_group_id": ENGINEER_GROUP_ID,
        "companies": _catalog_companies(),
        "employees": engineers,
        "issue_type": ISSUE_TYPE,
        "status_codes": STATUS_CODES,
        "typical": CATALOGS["typical"],
        "solution_method": CATALOGS["solution_method"],
        "complication_levels": CATALOGS.get("complication_levels") or ["+15", "+30"],
        "dry_run_default": DRY_RUN_DEFAULT,
        "intraservice_enrich_available": credentials_configured(),
        "okdesk_domain": domain,
    }


@app.get("/api/mfc/companies")
def companies(q: str = Query("", min_length=0)) -> dict[str, Any]:
    base = _catalog_companies()
    remote: list[dict] = []
    try:
        client = _require_client()
        try:
            for raw in client.search_companies(q, limit=50):
                item = _normalize_company(raw if isinstance(raw, dict) else {})
                if item:
                    remote.append(item)
        finally:
            client.close()
    except HTTPException:
        pass
    except Exception:
        pass
    items = _merge_named(base, remote)
    qn = (q or "").strip().casefold().replace("ё", "е")
    if qn:
        items = [
            x
            for x in items
            if qn in str(x["name"]).casefold().replace("ё", "е")
            or qn == str(x["id"])
        ]
    return {"items": items, "count": len(items)}


@app.get("/api/mfc/employees")
def employees(
    q: str = Query("", min_length=0),
    refresh: bool = False,
) -> dict[str, Any]:
    items = _load_engineer_employees(force=refresh)
    qn = (q or "").strip().casefold().replace("ё", "е")
    if qn:
        items = [
            x
            for x in items
            if qn in str(x["name"]).casefold().replace("ё", "е")
            or qn == str(x["id"])
        ]
    return {
        "items": items,
        "count": len(items),
        "engineer_group_id": ENGINEER_GROUP_ID,
        "active_only": True,
    }


@app.get("/api/mfc/intraservice/tasks")
def intraservice_tasks(
    q: str = Query("", min_length=0),
    pagesize: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
    if not credentials_configured():
        raise HTTPException(
            status_code=503,
            detail="IntraService credentials not configured (INTRASERVICE_USER/PASSWORD)",
        )
    try:
        items = list_tasks(search=q or None, page=page, pagesize=pagesize)
    except IntraserviceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"items": items, "count": len(items), "page": page}


@app.get("/api/mfc/objects")
def objects(
    q: str = Query("", min_length=0),
    limit: int = Query(200, ge=1, le=500),
    refresh: bool = False,
    company_id: Optional[int] = Query(None),
) -> dict[str, Any]:
    cid = int(company_id) if company_id is not None else COMPANY_ID
    all_objects = _load_objects(cid, force=refresh)
    q = (q or "").strip()
    if not q:
        items = sorted(all_objects, key=lambda x: str(x.get("name") or "").casefold())
        return {"items": items[:limit], "total": len(all_objects), "company_id": cid}
    matched = best_matches(q, all_objects, limit=limit, min_score=0.35)
    if len(matched) < 3:
        try:
            client = _require_client()
            remote = client.search_maintenance_entities(q)
            client.close()
            for raw in remote:
                item = _normalize_object(raw)
                item_cid = item.get("company_id")
                if item_cid is not None and int(item_cid) != cid:
                    continue
                if item["id"] and all(x["id"] != item["id"] for x in matched):
                    matched.append(item)
        except Exception:
            pass
    if not matched:
        items = sorted(all_objects, key=lambda x: str(x.get("name") or "").casefold())
        return {
            "items": items[:limit],
            "total": len(all_objects),
            "fallback_all": True,
            "query": q,
            "company_id": cid,
        }
    return {"items": matched[:limit], "total": len(all_objects), "company_id": cid}


@app.post("/api/mfc/parse")
def parse_endpoint(body: ParseRequest) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rows = [r.to_dict() for r in parse_list(body.text)]
    typicals = CATALOGS["typical"]
    aliases = CATALOGS.get("typical_aliases") or {}

    # Не блокируем разбор полной выгрузкой объектов: берём кэш выбранной компании.
    parse_company = int(body.company_id) if body.company_id is not None else COMPANY_ID
    objects = _cached_objects(parse_company)

    do_enrich = bool(body.enrich) and credentials_configured()

    # Параллельный enrich URL-строк (иначе 30+ заявок «висят» минутами)
    if do_enrich:
        to_enrich = [r for r in rows if r.get("external_id")]
        if to_enrich:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futs = {pool.submit(enrich_row, dict(r)): r for r in to_enrich}
                for fut in as_completed(futs):
                    original = futs[fut]
                    try:
                        enriched_row = fut.result()
                        original.clear()
                        original.update(enriched_row)
                    except Exception as e:
                        original["enrich_error"] = str(e)

    enriched = []
    for row in rows:
        suggested_object = None
        object_candidates: list[dict] = []
        if row.get("object_hint") and objects:
            object_candidates = best_matches(
                row["object_hint"], objects, limit=5, min_score=0.4
            )
            if object_candidates:
                suggested_object = object_candidates[0]

        suggested_typical = None
        if row.get("typical_hint"):
            suggested_typical = suggest_typical(
                row["typical_hint"], typicals, aliases
            )

        enriched.append(
            {
                **row,
                "suggested_object": suggested_object,
                "object_candidates": object_candidates,
                "suggested_typical": suggested_typical,
            }
        )
    return {
        "rows": enriched,
        "count": len(enriched),
        "enriched": do_enrich,
        "intraservice_enrich_available": credentials_configured(),
    }


@app.post("/api/mfc/batch")
def batch(body: BatchRequest) -> dict[str, Any]:
    dry_run = DRY_RUN_DEFAULT if body.dry_run is None else body.dry_run
    company_id = int(body.company_id) if body.company_id is not None else COMPANY_ID
    assignee_id = int(body.assignee_id) if body.assignee_id is not None else ASSIGNEE_ID
    results: list[dict[str, Any]] = []
    client: OkdeskClient | None = None
    if not dry_run:
        client = _require_client()

    try:
        for idx, item in enumerate(body.items):
            if not item.selected:
                results.append({"index": idx, "skipped": True, "reason": "not selected"})
                continue
            if not item.title.strip():
                results.append({"index": idx, "ok": False, "error": "empty title"})
                continue
            if not item.typical.strip() or not item.solution.strip():
                results.append(
                    {
                        "index": idx,
                        "ok": False,
                        "error": "typical and solution are required",
                    }
                )
                continue
            extra_err = _validate_extra_fields(item)
            if extra_err:
                results.append({"index": idx, "ok": False, "error": extra_err})
                continue

            description_parts = []
            if item.description:
                description_parts.append(item.description.strip())
            if item.external_url:
                description_parts.append(f"UCG: {item.external_url}")
            description = "\n".join(description_parts) or None

            issue_payload = {
                "title": item.title.strip()[:255],
                "description": description,
                "company_id": str(company_id),
                "assignee_id": str(assignee_id),
                "type": ISSUE_TYPE,
                "maintenance_entity_id": str(item.object_id),
                "custom_parameters": _build_custom_parameters(item),
            }
            comment = _build_close_comment(
                item.solution, body.batch_comment, item.external_url
            )

            if dry_run:
                results.append(
                    {
                        "index": idx,
                        "ok": True,
                        "dry_run": True,
                        "issue": issue_payload,
                        "status_codes": STATUS_CODES,
                        "comment": comment,
                    }
                )
                continue

            assert client is not None
            try:
                created = client.create_issue(issue_payload)
                issue_id = created.get("id")
                if not issue_id:
                    raise OkdeskError("create returned no id", body=created)
                for i, code in enumerate(STATUS_CODES):
                    client.change_status(
                        int(issue_id),
                        code,
                        comment=comment if i == 0 else None,
                        comment_public=False,
                    )
                results.append(
                    {
                        "index": idx,
                        "ok": True,
                        "issue_id": issue_id,
                        "title": item.title,
                        "statuses": STATUS_CODES,
                    }
                )
            except OkdeskError as e:
                results.append(
                    {
                        "index": idx,
                        "ok": False,
                        "error": str(e),
                        "detail": e.body,
                    }
                )
    finally:
        if client:
            client.close()

    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = sum(1 for r in results if r.get("ok") is False)
    return {
        "dry_run": dry_run,
        "ok": ok_n,
        "failed": fail_n,
        "results": results,
    }


@app.post("/api/mfc/objects/refresh")
def refresh_objects() -> dict[str, Any]:
    items = _load_objects(force=True)
    return {"total": len(items)}
