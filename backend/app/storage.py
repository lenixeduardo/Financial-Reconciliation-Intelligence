from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    rows_json TEXT NOT NULL,
                    columns_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reconciliations (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reconciliation_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reconciliation_templates_name
                ON reconciliation_templates(name);
                """
            )

    def save_dataset(self, dataset_id: str, label: str, filename: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO datasets(id,label,filename,rows_json,columns_json) VALUES(?,?,?,?,?)",
                (dataset_id, label, filename, json.dumps(rows, ensure_ascii=False), json.dumps(columns, ensure_ascii=False)),
            )

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "label": row["label"],
            "filename": row["filename"],
            "rows": json.loads(row["rows_json"]),
            "columns": json.loads(row["columns_json"]),
        }

    def save_reconciliation(self, reconciliation_id: str, payload: dict[str, Any], result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reconciliations(id,payload_json,result_json) VALUES(?,?,?)",
                (
                    reconciliation_id,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False),
                ),
            )

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reconciliations WHERE id=?", (reconciliation_id,)).fetchone()
        if not row:
            return None
        return {"payload": json.loads(row["payload_json"]), "result": json.loads(row["result_json"])}

    def save_template(self, template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM reconciliation_templates WHERE id=?", (template_id,)
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT OR REPLACE INTO reconciliation_templates
                (id,name,description,config_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    template_id,
                    payload["name"],
                    payload.get("description"),
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                    now,
                ),
            )
        return self.get_template(template_id)  # type: ignore[return-value]

    def list_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reconciliation_templates ORDER BY updated_at DESC, name ASC"
            ).fetchall()
        return [self._template_from_row(row) for row in rows]

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reconciliation_templates WHERE id=?", (template_id,)
            ).fetchone()
        return self._template_from_row(row) if row else None

    def delete_template(self, template_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM reconciliation_templates WHERE id=?", (template_id,))
        return cursor.rowcount > 0

    @staticmethod
    def _template_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["config_json"])
        return {
            **payload,
            "template_id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
