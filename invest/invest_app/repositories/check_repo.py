# -*- coding: utf-8 -*-
"""ذخیرهٔ دفتر چک روی همان پایگاه هر کاربر."""
from __future__ import annotations

import sqlite3
from typing import Any

_COLUMNS = (
    "id",
    "direction",
    "amount",
    "issue_date",
    "due_date",
    "check_number",
    "sayad_id",
    "bank_name",
    "branch",
    "counterparty",
    "purpose",
    "note",
    "status",
    "settled_date",
    "archived_at",
    "endorsed_to",
    "endorsed_for",
    "created_at",
    "updated_at",
)


def _as_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {key: (row[key] if key in keys else None) for key in _COLUMNS}


class CheckRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM checks ORDER BY due_date ASC, id ASC"
        ).fetchall()
        return [_as_dict(row) for row in rows]

    def get(self, check_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM checks WHERE id = ?",
            (int(check_id),),
        ).fetchone()
        return _as_dict(row) if row else None

    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        explicit = row.get("id")
        if explicit is None:
            cur = self._conn.execute(
                """
                INSERT INTO checks (
                    direction, amount, issue_date, due_date, check_number, sayad_id,
                    bank_name, branch, counterparty, purpose, note, status,
                    settled_date, archived_at, endorsed_to, endorsed_for, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["direction"], row["amount"], row["issue_date"], row["due_date"],
                    row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                    row["counterparty"], row["purpose"], row["note"], row["status"],
                    row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row["created_at"], row["updated_at"],
                ),
            )
            new_id = int(cur.lastrowid)
        else:
            self._conn.execute(
                """
                INSERT INTO checks (
                    id, direction, amount, issue_date, due_date, check_number, sayad_id,
                    bank_name, branch, counterparty, purpose, note, status,
                    settled_date, archived_at, endorsed_to, endorsed_for, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(explicit),
                    row["direction"], row["amount"], row["issue_date"], row["due_date"],
                    row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                    row["counterparty"], row["purpose"], row["note"], row["status"],
                    row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row["created_at"], row["updated_at"],
                ),
            )
            new_id = int(explicit)
        self._conn.commit()
        saved = self.get(new_id)
        if saved is None:
            raise RuntimeError("check insert vanished")
        return saved

    def update(self, check_id: int, row: dict[str, Any]) -> dict[str, Any] | None:
        cur = self._conn.execute(
            """
            UPDATE checks SET
                direction = ?, amount = ?, issue_date = ?, due_date = ?,
                check_number = ?, sayad_id = ?, bank_name = ?, branch = ?,
                counterparty = ?, purpose = ?, note = ?, status = ?,
                settled_date = ?, archived_at = ?, endorsed_to = ?, endorsed_for = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                row["direction"], row["amount"], row["issue_date"], row["due_date"],
                row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                row["counterparty"], row["purpose"], row["note"], row["status"],
                row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row["updated_at"], int(check_id),
            ),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(check_id)

    def delete(self, check_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM checks WHERE id = ?", (int(check_id),))
        self._conn.commit()
        return cur.rowcount > 0

    def replace_all(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            self._conn.execute("DELETE FROM checks")
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO checks (
                        id, direction, amount, issue_date, due_date, check_number, sayad_id,
                        bank_name, branch, counterparty, purpose, note, status,
                        settled_date, archived_at, endorsed_to, endorsed_for, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(row["id"]),
                        row["direction"], row["amount"], row["issue_date"], row["due_date"],
                        row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                        row["counterparty"], row["purpose"], row["note"], row["status"],
                        row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row["created_at"], row["updated_at"],
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.list_all()
