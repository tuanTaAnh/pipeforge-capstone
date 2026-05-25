from __future__ import annotations

import re


_FORBIDDEN_SQL_PATTERNS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\btruncate\b",
    r"\bcreate\b",
    r"\breplace\b",
    r"\battach\b",
    r"\bdetach\b",
    r"\bpragma\b",
    r"\bvacuum\b",
]


class UnsafeSqlError(ValueError):
    pass


def validate_select_sql(sql: str) -> None:
    normalized = re.sub(r"\s+", " ", sql.strip().lower())

    if not normalized.startswith("select") and not normalized.startswith("with"):
        raise UnsafeSqlError("Only SELECT / WITH queries are allowed for direct analytics answers.")

    for pattern in _FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, normalized):
            raise UnsafeSqlError(f"Unsafe SQL keyword detected: {pattern}")

    statements = [statement.strip() for statement in sql.strip().split(";") if statement.strip()]
    if len(statements) > 1:
        raise UnsafeSqlError("Only one SQL statement is allowed.")
