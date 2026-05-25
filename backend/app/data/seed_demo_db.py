from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from random import Random


DEFAULT_DB_PATH = "/app/data/pipeforge_demo.db"

REQUIRED_DEMO_TABLES = {
    "dim_customers",
    "dim_plans",
    "fact_subscriptions",
    "stripe_invoices",
    "stripe_payments",
}

REQUIRED_DEMO_COLUMNS = {
    "dim_customers": {
        "customer_id",
        "customer_name",
        "customer_segment",
        "country",
        "industry",
        "account_tier",
        "signup_date",
        "is_active",
    },
    "dim_plans": {
        "plan_id",
        "plan_name",
        "product_family",
        "billing_interval",
        "list_price",
        "currency",
        "is_active",
    },
    "fact_subscriptions": {
        "subscription_id",
        "customer_id",
        "plan_id",
        "status",
        "started_at",
        "ended_at",
        "mrr_amount",
        "currency",
        "quantity",
    },
    "stripe_invoices": {
        "invoice_id",
        "subscription_id",
        "customer_id",
        "invoice_amount",
        "currency",
        "status",
        "issued_at",
        "due_at",
        "paid_at",
        "customer_segment",
        "tax_amount",
        "discount_amount",
    },
    "stripe_payments": {
        "payment_id",
        "invoice_id",
        "subscription_id",
        "customer_id",
        "amount",
        "currency",
        "status",
        "paid_at",
        "plan_id",
        "customer_segment",
        "discount_amount",
        "refunded_at",
    },
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
    subscriptions = _build_subscription_seed_rows(customers, plans)
    invoices = _build_invoice_seed_rows(subscriptions, customers)
    payments = _build_payment_seed_rows(invoices, subscriptions, customers)

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
                customer_segment,
                country,
                industry,
                account_tier,
                signup_date,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            customers,
        )

        conn.executemany(
            """
            INSERT INTO dim_plans (
                plan_id,
                plan_name,
                product_family,
                billing_interval,
                list_price,
                currency,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            plans,
        )

        conn.executemany(
            """
            INSERT INTO fact_subscriptions (
                subscription_id,
                customer_id,
                plan_id,
                status,
                started_at,
                ended_at,
                mrr_amount,
                currency,
                quantity
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            subscriptions,
        )

        conn.executemany(
            """
            INSERT INTO stripe_invoices (
                invoice_id,
                subscription_id,
                customer_id,
                invoice_amount,
                currency,
                status,
                issued_at,
                due_at,
                paid_at,
                customer_segment,
                tax_amount,
                discount_amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            invoices,
        )

        conn.executemany(
            """
            INSERT INTO stripe_payments (
                payment_id,
                invoice_id,
                subscription_id,
                customer_id,
                amount,
                currency,
                status,
                paid_at,
                plan_id,
                customer_segment,
                discount_amount,
                refunded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            if not REQUIRED_DEMO_COLUMNS[table_name].issubset(actual_columns):
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
            customer_segment TEXT,
            country TEXT,
            industry TEXT,
            account_tier TEXT,
            signup_date TEXT,
            is_active INTEGER
        )
        """
    )


def _create_dim_plans_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE dim_plans (
            plan_id TEXT,
            plan_name TEXT,
            product_family TEXT,
            billing_interval TEXT,
            list_price REAL,
            currency TEXT,
            is_active INTEGER
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
            status TEXT,
            started_at TEXT,
            ended_at TEXT,
            mrr_amount REAL,
            currency TEXT,
            quantity INTEGER
        )
        """
    )


def _create_stripe_invoices_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE stripe_invoices (
            invoice_id TEXT,
            subscription_id TEXT,
            customer_id TEXT,
            invoice_amount REAL,
            currency TEXT,
            status TEXT,
            issued_at TEXT,
            due_at TEXT,
            paid_at TEXT,
            customer_segment TEXT,
            tax_amount REAL,
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
            subscription_id TEXT,
            customer_id TEXT,
            amount REAL,
            currency TEXT,
            status TEXT,
            paid_at TEXT,
            plan_id TEXT,
            customer_segment TEXT,
            discount_amount REAL,
            refunded_at TEXT
        )
        """
    )


def _build_customer_seed_rows() -> list[tuple]:
    rng = Random(100)

    segments = ["enterprise", "mid_market", "startup", "self_serve"]
    countries = ["US", "DE", "GB", "FR", "NL", "VN", "SG"]
    industries = ["fintech", "retail", "healthcare", "manufacturing", "software", "logistics"]
    tiers = ["strategic", "growth", "standard"]

    rows: list[tuple] = []

    for index in range(1, 61):
        customer_id = f"cus_{index:04d}"
        rows.append(
            (
                customer_id,
                f"Customer {index:04d}",
                rng.choice(segments),
                rng.choice(countries),
                rng.choice(industries),
                rng.choice(tiers),
                f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                1 if rng.random() > 0.12 else 0,
            )
        )

    rows.extend(
        [
            (
                "cus_0005",
                "Customer duplicate key",
                "enterprise",
                "US",
                "software",
                "strategic",
                "2025-02-01",
                1,
            ),
            (
                "cus_bad_country_001",
                "Customer Bad Country",
                "startup",
                "USA",
                "retail",
                "standard",
                "2025-04-11",
                1,
            ),
            (
                "cus_missing_segment_001",
                "Customer Missing Segment",
                None,
                "DE",
                "fintech",
                "growth",
                "2025-05-20",
                1,
            ),
        ]
    )

    return rows


def _build_plan_seed_rows() -> list[tuple]:
    return [
        ("plan_basic_m_usd", "Basic Monthly", "core_platform", "monthly", 49.0, "USD", 1),
        ("plan_pro_m_usd", "Pro Monthly", "core_platform", "monthly", 149.0, "USD", 1),
        ("plan_ent_m_usd", "Enterprise Monthly", "enterprise_suite", "monthly", 599.0, "USD", 1),
        ("plan_basic_y_eur", "Basic Annual", "core_platform", "annual", 499.0, "EUR", 1),
        ("plan_pro_y_eur", "Pro Annual", "core_platform", "annual", 1499.0, "EUR", 1),
        ("plan_ai_m_gbp", "AI Add-on Monthly", "ai_addon", "monthly", 199.0, "GBP", 1),
        # Intentional quality issues.
        ("plan_pro_m_usd", "Duplicate Pro Monthly", "core_platform", "monthly", 149.0, "USD", 1),
        ("plan_bad_interval_001", "Bad Interval Plan", "core_platform", "quarterly", 299.0, "USD", 1),
        ("plan_negative_price_001", "Negative Price Plan", "legacy", "monthly", -99.0, "USD", 0),
    ]


def _build_subscription_seed_rows(customers: list[tuple], plans: list[tuple]) -> list[tuple]:
    rng = Random(200)

    customer_ids = [
        row[0]
        for row in customers
        if str(row[0]).startswith("cus_") and row[2] is not None
    ]
    plan_ids = [
        row[0]
        for row in plans
        if str(row[0]).startswith("plan_") and row[3] in {"monthly", "annual"} and row[4] > 0
    ]

    rows: list[tuple] = []
    statuses = ["active", "active", "active", "past_due", "canceled", "trialing"]

    for index in range(1, 111):
        subscription_id = f"sub_{index:04d}"
        customer_id = rng.choice(customer_ids)
        plan_id = rng.choice(plan_ids)
        status = rng.choice(statuses)
        started_at = f"2026-{rng.randint(1, 5):02d}-{rng.randint(1, 25):02d}"
        ended_at = None
        if status == "canceled":
            ended_at = f"2026-{rng.randint(3, 6):02d}-{rng.randint(1, 28):02d}"
        quantity = rng.choice([1, 1, 1, 2, 3, 5])
        plan_price = next(float(plan[4]) for plan in plans if plan[0] == plan_id)
        plan_currency = next(str(plan[5]) for plan in plans if plan[0] == plan_id)
        billing_interval = next(str(plan[3]) for plan in plans if plan[0] == plan_id)
        monthly_base = round(plan_price / 12, 2) if billing_interval == "annual" else plan_price
        mrr_amount = round(monthly_base * quantity, 2)

        rows.append(
            (
                subscription_id,
                customer_id,
                plan_id,
                status,
                started_at,
                ended_at,
                mrr_amount,
                plan_currency,
                quantity,
            )
        )

    rows.extend(
        [
            (
                "sub_0005",
                "cus_0005",
                "plan_pro_m_usd",
                "active",
                "2026-01-05",
                None,
                149.0,
                "USD",
                1,
            ),
            (
                "sub_missing_customer_001",
                "cus_does_not_exist_001",
                "plan_basic_m_usd",
                "active",
                "2026-02-01",
                None,
                49.0,
                "USD",
                1,
            ),
            (
                "sub_missing_plan_001",
                "cus_0010",
                "plan_does_not_exist_001",
                "active",
                "2026-02-02",
                None,
                199.0,
                "USD",
                1,
            ),
            (
                "sub_invalid_status_001",
                "cus_0011",
                "plan_pro_m_usd",
                "paused",
                "2026-02-03",
                None,
                149.0,
                "USD",
                1,
            ),
            (
                "sub_negative_mrr_001",
                "cus_0012",
                "plan_pro_m_usd",
                "active",
                "2026-02-04",
                None,
                -149.0,
                "USD",
                1,
            ),
        ]
    )

    return rows


def _build_invoice_seed_rows(
    subscriptions: list[tuple],
    customers: list[tuple],
) -> list[tuple]:
    rng = Random(300)

    customer_segment_by_id = {
        row[0]: row[2]
        for row in customers
        if row[2] is not None
    }

    valid_subscriptions = [
        row
        for row in subscriptions
        if str(row[0]).startswith("sub_")
        and str(row[1]).startswith("cus_")
        and row[6] > 0
        and row[7] in {"USD", "EUR", "GBP"}
    ]

    rows: list[tuple] = []

    for index in range(1, 161):
        subscription = rng.choice(valid_subscriptions)
        subscription_id = subscription[0]
        customer_id = subscription[1]
        mrr_amount = float(subscription[6])
        currency = str(subscription[7])
        status = rng.choice(["open", "paid", "paid", "paid", "void", "uncollectible"])
        issued_month = rng.randint(1, 6)
        issued_day = rng.randint(1, 24)
        issued_at = f"2026-{issued_month:02d}-{issued_day:02d}T09:00:00"
        due_at = f"2026-{issued_month:02d}-{min(28, issued_day + 10):02d}T23:59:00"
        paid_at = None
        if status == "paid":
            paid_at = f"2026-{issued_month:02d}-{min(28, issued_day + rng.randint(1, 10)):02d}T11:00:00"

        discount_amount = None if rng.random() < 0.26 else float(rng.choice([0, 10, 20, 50]))
        tax_amount = float(rng.choice([0, 5, 10, 20, 50]))
        invoice_amount = round(mrr_amount + tax_amount - (discount_amount or 0), 2)
        if invoice_amount <= 0:
            invoice_amount = round(mrr_amount, 2)

        rows.append(
            (
                f"inv_{index:04d}",
                subscription_id,
                customer_id,
                invoice_amount,
                currency,
                status,
                issued_at,
                due_at,
                paid_at,
                customer_segment_by_id.get(customer_id),
                tax_amount,
                discount_amount,
            )
        )

    rows.extend(
        [
            (
                "inv_0005",
                "sub_0005",
                "cus_0005",
                299.0,
                "USD",
                "paid",
                "2026-03-01T09:00:00",
                "2026-03-15T23:59:00",
                "2026-03-10T11:00:00",
                "startup",
                20.0,
                None,
            ),
            (
                "inv_missing_subscription_001",
                "sub_does_not_exist_001",
                "cus_0202",
                149.0,
                "USD",
                "paid",
                "2026-03-02T09:00:00",
                "2026-03-16T23:59:00",
                "2026-03-12T11:00:00",
                "self_serve",
                10.0,
                0.0,
            ),
            (
                "inv_invalid_status_001",
                "sub_0008",
                "cus_0202",
                149.0,
                "USD",
                "cancelled",
                "2026-03-02T09:00:00",
                "2026-03-16T23:59:00",
                None,
                "self_serve",
                10.0,
                0.0,
            ),
            (
                "inv_invalid_currency_001",
                "sub_0009",
                "cus_0203",
                199.0,
                "EURO",
                "open",
                "2026-03-03T09:00:00",
                "2026-03-17T23:59:00",
                None,
                "enterprise",
                20.0,
                None,
            ),
            (
                "inv_negative_amount_001",
                "sub_0010",
                "cus_0204",
                -99.0,
                "EUR",
                "paid",
                "2026-03-04T09:00:00",
                "2026-03-18T23:59:00",
                "2026-03-12T11:00:00",
                "startup",
                0.0,
                0.0,
            ),
            (
                "inv_missing_issued_at_001",
                "sub_0011",
                "cus_0205",
                399.0,
                "GBP",
                "open",
                None,
                "2026-03-19T23:59:00",
                None,
                "enterprise",
                30.0,
                None,
            ),
            (
                "inv_paid_missing_paid_at_001",
                "sub_0012",
                "cus_0206",
                249.0,
                "USD",
                "paid",
                "2026-03-06T09:00:00",
                "2026-03-20T23:59:00",
                None,
                "self_serve",
                10.0,
                0.0,
            ),
            (
                "inv_bad_tax_001",
                "sub_0013",
                "cus_0207",
                20.0,
                "EUR",
                "paid",
                "2026-03-07T09:00:00",
                "2026-03-21T23:59:00",
                "2026-03-13T11:00:00",
                "startup",
                30.0,
                0.0,
            ),
            (
                "inv_missing_segment_001",
                "sub_0014",
                "cus_0208",
                199.0,
                "USD",
                "open",
                "2026-03-08T09:00:00",
                "2026-03-22T23:59:00",
                None,
                None,
                10.0,
                None,
            ),
        ]
    )

    return rows


def _build_payment_seed_rows(
    invoice_rows: list[tuple],
    subscription_rows: list[tuple],
    customer_rows: list[tuple],
) -> list[tuple]:
    rng = Random(400)

    currencies = ["USD", "EUR", "GBP"]
    plans_by_subscription = {
        row[0]: row[2]
        for row in subscription_rows
    }
    customer_segment_by_id = {
        row[0]: row[2]
        for row in customer_rows
        if row[2] is not None
    }

    valid_invoice_rows = [
        row
        for row in invoice_rows
        if str(row[0]).startswith("inv_")
        and str(row[1]).startswith("sub_")
        and row[4] in currencies
        and row[3] > 0
    ]

    rows: list[tuple] = []

    for index in range(1, 181):
        linked_invoice = rng.choice(valid_invoice_rows)

        invoice_id = linked_invoice[0] if rng.random() < 0.80 else None
        subscription_id = linked_invoice[1] if invoice_id else None
        customer_id = linked_invoice[2] if invoice_id else f"cus_{rng.randint(1, 60):04d}"
        invoice_amount = float(linked_invoice[3])
        currency = linked_invoice[4] if invoice_id else rng.choice(currencies)

        amount_pattern = rng.random()
        if invoice_id and amount_pattern < 0.55:
            amount = invoice_amount
        elif invoice_id and amount_pattern < 0.78:
            amount = round(invoice_amount * rng.choice([0.25, 0.5, 0.75]), 2)
        elif invoice_id and amount_pattern < 0.88:
            amount = round(invoice_amount * rng.choice([1.1, 1.2]), 2)
        else:
            amount = float(rng.choice([19, 29, 49, 99, 199, 499]))

        status = rng.choice(["paid", "paid", "paid", "failed", "refunded"])
        paid_at = f"2026-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}T10:00:00"
        plan_id = plans_by_subscription.get(subscription_id) if subscription_id else rng.choice(["plan_basic_m_usd", "plan_pro_m_usd", "plan_ai_m_gbp"])
        customer_segment = customer_segment_by_id.get(customer_id)
        discount_amount = None if rng.random() < 0.40 else float(rng.choice([0, 5, 10, 20]))
        refunded_at = None

        if status == "refunded":
            refunded_at = f"2026-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}T12:00:00"

        rows.append(
            (
                f"pay_{index:04d}",
                invoice_id,
                subscription_id,
                customer_id,
                amount,
                currency,
                status,
                paid_at,
                plan_id,
                customer_segment,
                discount_amount,
                refunded_at,
            )
        )

    rows.extend(
        [
            (
                "pay_0005",
                "inv_0005",
                "sub_0005",
                "cus_0005",
                99.0,
                "USD",
                "paid",
                "2026-03-11T10:00:00",
                "plan_pro_m_usd",
                "startup",
                None,
                None,
            ),
            (
                "pay_invalid_status_001",
                "inv_0008",
                "sub_0008",
                "cus_0100",
                49.0,
                "USD",
                "cancelled",
                "2026-03-12T10:00:00",
                "plan_basic_m_usd",
                "self_serve",
                0.0,
                None,
            ),
            (
                "pay_invalid_currency_001",
                "inv_0009",
                "sub_0009",
                "cus_0101",
                79.0,
                "US",
                "paid",
                "2026-03-13T10:00:00",
                "plan_pro_m_usd",
                "startup",
                None,
                None,
            ),
            (
                "pay_negative_amount_001",
                "inv_0010",
                "sub_0010",
                "cus_0102",
                -29.0,
                "EUR",
                "paid",
                "2026-03-14T10:00:00",
                "plan_basic_y_eur",
                "self_serve",
                0.0,
                None,
            ),
            (
                "pay_bad_discount_001",
                "inv_0011",
                "sub_0011",
                "cus_0103",
                20.0,
                "GBP",
                "paid",
                "2026-03-15T10:00:00",
                "plan_ai_m_gbp",
                "startup",
                30.0,
                None,
            ),
            (
                "pay_refund_missing_date_001",
                "inv_0012",
                "sub_0012",
                "cus_0104",
                199.0,
                "USD",
                "refunded",
                "2026-03-16T10:00:00",
                "plan_ent_m_usd",
                "enterprise",
                0.0,
                None,
            ),
            (
                "pay_paid_missing_date_001",
                "inv_0013",
                "sub_0013",
                "cus_0105",
                49.0,
                "USD",
                "paid",
                None,
                "plan_pro_m_usd",
                "startup",
                None,
                None,
            ),
            (
                "pay_missing_segment_001",
                "inv_0014",
                "sub_0014",
                "cus_0106",
                99.0,
                "EUR",
                "paid",
                "2026-03-17T10:00:00",
                "plan_pro_y_eur",
                None,
                0.0,
                None,
            ),
            (
                "pay_unmatched_invoice_001",
                "inv_does_not_exist_001",
                None,
                "cus_0301",
                149.0,
                "USD",
                "paid",
                "2026-03-18T10:00:00",
                "plan_pro_m_usd",
                "startup",
                0.0,
                None,
            ),
            (
                "pay_no_invoice_001",
                None,
                None,
                "cus_0302",
                79.0,
                "EUR",
                "paid",
                "2026-03-19T10:00:00",
                "plan_basic_y_eur",
                "self_serve",
                0.0,
                None,
            ),
            (
                "pay_currency_mismatch_001",
                "inv_0001",
                "sub_0001",
                "cus_0303",
                99.0,
                "GBP",
                "paid",
                "2026-03-20T10:00:00",
                "plan_pro_m_usd",
                "enterprise",
                0.0,
                None,
            ),
        ]
    )

    return rows


if __name__ == "__main__":
    created_path = reset_demo_database()
    print(f"Seeded demo database: {created_path}")
