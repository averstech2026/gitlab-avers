#!/usr/bin/env python3
"""Ensure trigger column «В работе (очередь Git)» on boards that have «В работе».

- Renames «В работе» → «В работе (очередь Git)» if needed
- Removes leftover «В разработку» columns (empty or after moving cards is caller's problem)

Usage:
  PLANKA_EMAIL=... PLANKA_PASSWORD=... python3 ensure_ready_lists.py
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("PLANKA_BASE_URL", "https://board.averstech.ru").rstrip("/")
READY = os.environ.get("PLANKA_READY_LIST_NAME", "В работе (очередь Git)")
LEGACY_READY = "В разработку"
RENAME_FROM = "В работе"

CTX = ssl.create_default_context()


def req(method, path, token=None, data=None):
    url = BASE + path
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def credentials() -> tuple[str, str]:
    email = os.environ.get("PLANKA_EMAIL")
    password = os.environ.get("PLANKA_PASSWORD")
    if email and password:
        return email, password
    secrets = Path("/Users/delykov/Documents/planka-prod/SECRETS.local.md")
    if secrets.exists():
        text = secrets.read_text(encoding="utf-8")
        email = re.search(r"DEFAULT_ADMIN_EMAIL \| `([^`]+)`", text).group(1)
        password = re.search(r"DEFAULT_ADMIN_PASSWORD \| `([^`]+)`", text).group(1)
        return email, password
    raise SystemExit("Set PLANKA_EMAIL and PLANKA_PASSWORD")


def main() -> None:
    email, password = credentials()
    st, auth = req(
        "POST",
        "/api/access-tokens",
        data={"emailOrUsername": email, "password": password},
    )
    if st != 200:
        raise SystemExit(f"auth failed: {st} {auth}")
    token = auth["item"]
    projects = req("GET", "/api/projects", token=token)[1]
    proj_by_id = {p["id"]: p for p in projects["items"]}
    boards = (projects.get("included") or {}).get("boards") or []

    for b in boards:
        pname = proj_by_id.get(b["projectId"], {}).get("name", "?")
        data = req("GET", f"/api/boards/{b['id']}", token=token)[1]
        lists = [l for l in ((data.get("included") or {}).get("lists") or []) if l.get("name")]
        for lst in lists:
            if lst["name"] == LEGACY_READY:
                st, _ = req("DELETE", f"/api/lists/{lst['id']}", token=token)
                print(f"DEL [{st}] {pname} / {b['name']} | {LEGACY_READY!r}")
            elif lst["name"] == RENAME_FROM:
                st, _ = req(
                    "PATCH",
                    f"/api/lists/{lst['id']}",
                    token=token,
                    data={"name": READY},
                )
                print(f"REN [{st}] {pname} / {b['name']} | → {READY!r}")
            elif lst["name"] == READY:
                print(f"OK  {pname} / {b['name']} | {READY!r}")


if __name__ == "__main__":
    main()
