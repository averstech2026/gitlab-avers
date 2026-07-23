from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    card_id TEXT PRIMARY KEY,
                    issue_iid INTEGER NOT NULL,
                    issue_id INTEGER,
                    issue_url TEXT,
                    list_id TEXT,
                    board_id TEXT,
                    project_name TEXT,
                    board_name TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_links_issue_iid ON links(issue_iid)"
            )

    def get_by_card(self, card_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM links WHERE card_id = ?", (str(card_id),)
            ).fetchone()
            return dict(row) if row else None

    def get_by_issue_iid(self, issue_iid: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM links WHERE issue_iid = ?", (int(issue_iid),)
            ).fetchone()
            return dict(row) if row else None

    def upsert(
        self,
        *,
        card_id: str,
        issue_iid: int,
        issue_id: int | None,
        issue_url: str,
        list_id: str | None,
        board_id: str | None,
        project_name: str | None,
        board_name: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO links (
                    card_id, issue_iid, issue_id, issue_url,
                    list_id, board_id, project_name, board_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    issue_iid = excluded.issue_iid,
                    issue_id = excluded.issue_id,
                    issue_url = excluded.issue_url,
                    list_id = excluded.list_id,
                    board_id = excluded.board_id,
                    project_name = excluded.project_name,
                    board_name = excluded.board_name
                """,
                (
                    str(card_id),
                    int(issue_iid),
                    issue_id,
                    issue_url,
                    list_id,
                    board_id,
                    project_name,
                    board_name,
                ),
            )
