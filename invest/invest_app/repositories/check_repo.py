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
    "kind",
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
        payments = self._payments_by_check()
        out = []
        for row in rows:
            item = _as_dict(row)
            item["payments"] = payments.get(int(item["id"]), [])
            out.append(item)
        return out

    def get(self, check_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM checks WHERE id = ?",
            (int(check_id),),
        ).fetchone()
        if row is None:
            return None
        item = _as_dict(row)
        item["payments"] = self._payments_by_check().get(int(check_id), [])
        return item

    def _payments_by_check(self) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        rows = self._conn.execute(
            "SELECT id, check_id, amount, paid_at, note, created_at "
            "FROM check_payments ORDER BY paid_at ASC, id ASC"
        ).fetchall()
        for row in rows:
            check_id = int(row["check_id"])
            grouped.setdefault(check_id, []).append({
                "id": int(row["id"]),
                "check_id": check_id,
                "amount": row["amount"],
                "paid_at": str(row["paid_at"] or ""),
                "note": str(row["note"] or ""),
                "created_at": str(row["created_at"] or ""),
            })
        return grouped

    def _write_payments(self, check_id: int, payments: list[dict[str, Any]]) -> None:
        self._conn.execute(
            "DELETE FROM check_payments WHERE check_id = ?",
            (int(check_id),),
        )
        for payment in payments:
            self._conn.execute(
                """
                INSERT INTO check_payments (
                    id, check_id, amount, paid_at, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payment.get("id"),
                    int(check_id),
                    payment["amount"],
                    payment["paid_at"],
                    payment.get("note") or "",
                    payment.get("created_at") or "",
                ),
            )

    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        explicit = row.get("id")
        if explicit is None:
            cur = self._conn.execute(
                """
                INSERT INTO checks (
                    direction, amount, issue_date, due_date, check_number, sayad_id,
                    bank_name, branch, counterparty, purpose, note, status,
                    settled_date, archived_at, endorsed_to, endorsed_for, kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["direction"], row["amount"], row["issue_date"], row["due_date"],
                    row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                    row["counterparty"], row["purpose"], row["note"], row["status"],
                    row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row.get("kind") or "check", row["created_at"], row["updated_at"],
                ),
            )
            new_id = int(cur.lastrowid)
        else:
            self._conn.execute(
                """
                INSERT INTO checks (
                    id, direction, amount, issue_date, due_date, check_number, sayad_id,
                    bank_name, branch, counterparty, purpose, note, status,
                    settled_date, archived_at, endorsed_to, endorsed_for, kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(explicit),
                    row["direction"], row["amount"], row["issue_date"], row["due_date"],
                    row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                    row["counterparty"], row["purpose"], row["note"], row["status"],
                    row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row.get("kind") or "check", row["created_at"], row["updated_at"],
                ),
            )
            new_id = int(explicit)
        self._write_payments(new_id, list(row.get("payments") or []))
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
                settled_date = ?, archived_at = ?, endorsed_to = ?, endorsed_for = ?, kind = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                row["direction"], row["amount"], row["issue_date"], row["due_date"],
                row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                row["counterparty"], row["purpose"], row["note"], row["status"],
                row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row.get("kind") or "check", row["updated_at"], int(check_id),
            ),
        )
        if cur.rowcount:
            self._write_payments(int(check_id), list(row.get("payments") or []))
        self._conn.commit()
        if cur.rowcount == 0:
            return None
        return self.get(check_id)

    def delete(self, check_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM checks WHERE id = ?", (int(check_id),))
        if cur.rowcount:
            self._conn.execute(
                "DELETE FROM check_payments WHERE check_id = ?",
                (int(check_id),),
            )
        self._conn.commit()
        return cur.rowcount > 0

    def replace_all(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            self._conn.execute("DELETE FROM check_payments")
            self._conn.execute("DELETE FROM checks")
            for row in rows:
                self._conn.execute(
                    """
                    INSERT INTO checks (
                        id, direction, amount, issue_date, due_date, check_number, sayad_id,
                        bank_name, branch, counterparty, purpose, note, status,
                        settled_date, archived_at, endorsed_to, endorsed_for, kind, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(row["id"]),
                        row["direction"], row["amount"], row["issue_date"], row["due_date"],
                        row["check_number"], row["sayad_id"], row["bank_name"], row["branch"],
                        row["counterparty"], row["purpose"], row["note"], row["status"],
                        row.get("settled_date"), row.get("archived_at"), row.get("endorsed_to") or "", row.get("endorsed_for") or "", row.get("kind") or "check", row["created_at"], row["updated_at"],
                    ),
                )
                self._write_payments(int(row["id"]), list(row.get("payments") or []))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.list_all()
