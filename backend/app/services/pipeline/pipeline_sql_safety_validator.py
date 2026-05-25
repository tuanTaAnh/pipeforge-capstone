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


class UnsafePipelineSqlError(ValueError):
    pass


def validate_pipeline_model_sql(sql: str) -> None:
    """
    Validate a compiled pipeline model SQL statement before the demo executor wraps it as:

        CREATE TABLE <model_name> AS <compiled_sql>

    Model SQL is allowed to start with normal SQL comments, for example:

        -- Staging model
        select ...

    After leading comments are removed, the executable model must still start with
    SELECT or WITH. This keeps generated model artifacts read-only and prevents
    model files from directly mutating the source database or the demo mart.
    """
    if not sql or not sql.strip():
        raise UnsafePipelineSqlError("Pipeline model SQL is empty.")

    executable_sql = strip_leading_sql_comments(sql).strip()

    if not executable_sql:
        raise UnsafePipelineSqlError("Pipeline model SQL is empty after removing comments.")

    normalized_start = re.sub(r"\s+", " ", executable_sql.lower())

    if not normalized_start.startswith("select") and not normalized_start.startswith("with"):
        raise UnsafePipelineSqlError("Pipeline model SQL must start with SELECT or WITH.")

    comment_free_sql = strip_sql_comments(sql)
    keyword_scan_sql = mask_sql_quoted_literals(comment_free_sql)
    normalized_keyword_scan = re.sub(r"\s+", " ", keyword_scan_sql.strip().lower())

    for pattern in _FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, normalized_keyword_scan):
            keyword = pattern.replace("\\b", "")
            raise UnsafePipelineSqlError(f"Unsafe SQL keyword detected in model SQL: {keyword}")

    statements = split_sql_statements(comment_free_sql)

    if len(statements) > 1:
        raise UnsafePipelineSqlError("Only one SQL statement is allowed per pipeline model.")


def strip_leading_sql_comments(sql: str) -> str:
    """
    Remove only comments and whitespace before the first executable SQL token.

    Supports:
    - line comments:  -- comment
    - block comments: /* comment */
    """
    index = 0
    length = len(sql)

    while index < length:
        while index < length and sql[index].isspace():
            index += 1

        if sql.startswith("--", index):
            newline_index = sql.find("\n", index + 2)
            if newline_index == -1:
                return ""
            index = newline_index + 1
            continue

        if sql.startswith("/*", index):
            end_index = sql.find("*/", index + 2)
            if end_index == -1:
                raise UnsafePipelineSqlError("Unclosed SQL block comment.")
            index = end_index + 2
            continue

        break

    return sql[index:]


def strip_sql_comments(sql: str) -> str:
    """
    Remove SQL comments while preserving quoted strings.

    This prevents comments such as "-- drop table" from being detected as unsafe
    executable SQL, while still letting the validator inspect the real statement.
    """
    result: list[str] = []
    index = 0
    length = len(sql)
    quote: str | None = None

    while index < length:
        char = sql[index]

        if quote:
            result.append(char)

            if char == quote:
                # SQL escapes single quotes by doubling them: 'it''s'
                if quote == "'" and index + 1 < length and sql[index + 1] == "'":
                    result.append(sql[index + 1])
                    index += 2
                    continue

                quote = None

            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            result.append(char)
            index += 1
            continue

        if char == "[":
            end_index = sql.find("]", index + 1)
            if end_index == -1:
                result.append(char)
                index += 1
                continue

            result.append(sql[index : end_index + 1])
            index = end_index + 1
            continue

        if sql.startswith("--", index):
            newline_index = sql.find("\n", index + 2)
            if newline_index == -1:
                break

            result.append("\n")
            index = newline_index + 1
            continue

        if sql.startswith("/*", index):
            end_index = sql.find("*/", index + 2)
            if end_index == -1:
                raise UnsafePipelineSqlError("Unclosed SQL block comment.")

            # Preserve spacing so tokens on either side of the comment do not merge.
            result.append(" ")
            index = end_index + 2
            continue

        result.append(char)
        index += 1

    return "".join(result)


def mask_sql_quoted_literals(sql: str) -> str:
    """
    Replace quoted strings/identifiers with spaces before keyword scanning.

    Example:
        select 'drop' as label

    should not be blocked just because the string literal contains the word "drop".
    """
    result: list[str] = []
    index = 0
    length = len(sql)
    quote: str | None = None

    while index < length:
        char = sql[index]

        if quote:
            if char == quote:
                if quote == "'" and index + 1 < length and sql[index + 1] == "'":
                    result.append(" ")
                    result.append(" ")
                    index += 2
                    continue

                result.append(" ")
                quote = None
                index += 1
                continue

            result.append(" ")
            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            result.append(" ")
            index += 1
            continue

        if char == "[":
            end_index = sql.find("]", index + 1)
            if end_index == -1:
                result.append(char)
                index += 1
                continue

            result.append(" " * (end_index - index + 1))
            index = end_index + 1
            continue

        result.append(char)
        index += 1

    return "".join(result)


def split_sql_statements(sql: str) -> list[str]:
    """
    Split statements on semicolons that are not inside quoted strings.

    A trailing semicolon is allowed, but multiple executable statements are not.
    """
    statements: list[str] = []
    current: list[str] = []
    index = 0
    length = len(sql)
    quote: str | None = None

    while index < length:
        char = sql[index]

        if quote:
            current.append(char)

            if char == quote:
                if quote == "'" and index + 1 < length and sql[index + 1] == "'":
                    current.append(sql[index + 1])
                    index += 2
                    continue

                quote = None

            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            index += 1
            continue

        if char == "[":
            end_index = sql.find("]", index + 1)
            if end_index == -1:
                current.append(char)
                index += 1
                continue

            current.append(sql[index : end_index + 1])
            index = end_index + 1
            continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    final_statement = "".join(current).strip()

    if final_statement:
        statements.append(final_statement)

    return statements