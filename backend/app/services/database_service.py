from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.data.seed_demo_db import ensure_demo_database


DEFAULT_DB_PATH = "/app/data/pipeforge_demo.db"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_database_path() -> Path:
    path = Path(os.getenv("PIPEFORGE_DEMO_DB_PATH", DEFAULT_DB_PATH))
    ensure_demo_database(path)
    return path


def get_connection() -> sqlite3.Connection:
    db_path = get_database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_PATTERN.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier}")

    return f'"{identifier}"'


def table_exists(table_name: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (table_name,),
        ).fetchone()

    return row is not None


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(query, params).fetchone()

    return dict(row) if row else None