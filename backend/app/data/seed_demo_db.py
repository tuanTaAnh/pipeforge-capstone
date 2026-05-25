from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = "/app/data/pipeforge_demo.db"

REQUIRED_DEMO_TABLES = {
    "dim_customers",
    "dim_plans",
    "fact_subscriptions",
    "stripe_invoices",
    "stripe_payments",
}

REQUIRED_DEMO_COLUMNS = {
    "dim_customers": {"customer_id", "customer_name", "customer_segment"},
    "dim_plans": {"plan_id", "plan_name"},
    "fact_subscriptions": {"subscription_id", "customer_id", "plan_id", "mrr_amount"},
    "stripe_invoices": {"invoice_id", "subscription_id", "invoice_month", "invoice_amount", "discount_amount"},
    "stripe_payments": {"payment_id", "invoice_id", "payment_month", "successful_amount", "refund_amount"},
}


def get_demo_db_path() -> Path:
    return Path(os.getenv("PIPEFORGE_DEMO_DB_PATH", DEFAULT_DB_PATH))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def reset_demo_database(db_path: Path | None = None) -> Path:
    path = db_path or get_demo_db_path()

    customers = _build_customer_seed_rows()
    plans = _build_plan_seed_rows()
    subscriptions = _build_subscription_seed_rows()
    invoices = _build_invoice_seed_rows()
    payments = _build_payment_seed_rows()

    with _connect(path) as conn:
        for table_name in [
            "stripe_payments",
            "stripe_invoices",
            "fact_subscriptions",
            "dim_plans",
            "dim_customers",
        ]:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        _create_dim_customers_table(conn)
        _create_dim_plans_table(conn)
        _create_fact_subscriptions_table(conn)
        _create_stripe_invoices_table(conn)
        _create_stripe_payments_table(conn)

        conn.executemany(
            """
            INSERT INTO dim_customers (
                customer_id,
                customer_name,
                customer_segment
            )
            VALUES (?, ?, ?)
            """,
            customers,
        )

        conn.executemany(
            """
            INSERT INTO dim_plans (
                plan_id,
                plan_name
            )
            VALUES (?, ?)
            """,
            plans,
        )

        conn.executemany(
            """
            INSERT INTO fact_subscriptions (
                subscription_id,
                customer_id,
                plan_id,
                mrr_amount
            )
            VALUES (?, ?, ?, ?)
            """,
            subscriptions,
        )

        conn.executemany(
            """
            INSERT INTO stripe_invoices (
                invoice_id,
                subscription_id,
                invoice_month,
                invoice_amount,
                discount_amount
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            invoices,
        )

        conn.executemany(
            """
            INSERT INTO stripe_payments (
                payment_id,
                invoice_id,
                payment_month,
                successful_amount,
                refund_amount
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            payments,
        )

        conn.commit()

    return path


def ensure_demo_database(db_path: Path | None = None) -> Path:
    path = db_path or get_demo_db_path()

    if not path.exists():
        return reset_demo_database(path)

    with _connect(path) as conn:
        existing_tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        if not REQUIRED_DEMO_TABLES.issubset(existing_tables):
            return reset_demo_database(path)

        for table_name in REQUIRED_DEMO_TABLES:
            actual_columns = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }

            if actual_columns != REQUIRED_DEMO_COLUMNS[table_name]:
                return reset_demo_database(path)

            row_count = conn.execute(
                f"SELECT COUNT(*) AS count FROM {table_name}"
            ).fetchone()["count"]

            if row_count == 0:
                return reset_demo_database(path)

    return path


def _create_dim_customers_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE dim_customers (
            customer_id TEXT,
            customer_name TEXT,
            customer_segment TEXT
        )
        """
    )


def _create_dim_plans_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE dim_plans (
            plan_id TEXT,
            plan_name TEXT
        )
        """
    )


def _create_fact_subscriptions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE fact_subscriptions (
            subscription_id TEXT,
            customer_id TEXT,
            plan_id TEXT,
            mrr_amount REAL
        )
        """
    )


def _create_stripe_invoices_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE stripe_invoices (
            invoice_id TEXT,
            subscription_id TEXT,
            invoice_month TEXT,
            invoice_amount REAL,
            discount_amount REAL
        )
        """
    )


def _create_stripe_payments_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE stripe_payments (
            payment_id TEXT,
            invoice_id TEXT,
            payment_month TEXT,
            successful_amount REAL,
            refund_amount REAL
        )
        """
    )


def _build_customer_seed_rows() -> list[tuple]:
    return [
        ("cus_001", "Acme GmbH", "enterprise"),
        ("cus_002", "Northstar Labs", "mid_market"),
        ("cus_003", "BrightApps", "startup"),
        ("cus_004", "SoloDesk", "self_serve"),
        ("cus_005", "Helios Manufacturing", "enterprise"),
        ("cus_006", "River Analytics", "mid_market"),
    ]


def _build_plan_seed_rows() -> list[tuple]:
    return [
        ("plan_basic", "Basic"),
        ("plan_pro", "Pro"),
        ("plan_enterprise", "Enterprise"),
        ("plan_ai_addon", "AI Add-on"),
    ]


def _build_subscription_seed_rows() -> list[tuple]:
    return [
        ("sub_001", "cus_001", "plan_enterprise", 599.0),
        ("sub_002", "cus_002", "plan_pro", 149.0),
        ("sub_003", "cus_003", "plan_basic", 49.0),
        ("sub_004", "cus_004", "plan_basic", 49.0),
        ("sub_005", "cus_005", "plan_enterprise", 599.0),
        ("sub_006", "cus_006", "plan_pro", 149.0),
    ]


def _build_invoice_seed_rows() -> list[tuple]:
    return [
        ("inv_001", "sub_001", "2026-03", 599.0, 0.0),
        ("inv_002", "sub_002", "2026-03", 149.0, 20.0),
        ("inv_003", "sub_003", "2026-03", 49.0, None),
        ("inv_004", "sub_004", "2026-03", 49.0, 0.0),
        ("inv_005", "sub_005", "2026-03", 599.0, 100.0),
        ("inv_006", "sub_006", "2026-04", 149.0, 0.0),
        ("inv_007", "sub_001", "2026-04", 599.0, 50.0),
        ("inv_008", "sub_002", "2026-04", 149.0, None),
    ]


def _build_payment_seed_rows() -> list[tuple]:
    return [
        ("pay_001", "inv_001", "2026-03", 599.0, 0.0),
        ("pay_002", "inv_002", "2026-03", 149.0, 0.0),
        ("pay_003", "inv_004", "2026-03", 49.0, 10.0),
        ("pay_004", "inv_005", "2026-03", 599.0, 0.0),
        ("pay_005", "inv_006", "2026-04", 149.0, 0.0),
        ("pay_006", "inv_007", "2026-04", 599.0, 0.0),
        ("pay_007", "inv_008", "2026-04", 149.0, 0.0),
    ]


if __name__ == "__main__":
    created_path = reset_demo_database()
    print(f"Seeded demo database: {created_path}")
