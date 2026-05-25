from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.database_service import fetch_one
from app.services.semantic_layer_loader import load_dimensions, load_metrics, load_time_semantics
from app.services.semantic_query_parser import SemanticQueryPlan


DATE_FORMATS = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]


def build_sql_query(plan: SemanticQueryPlan) -> dict[str, Any]:
    if not plan.metric_name:
        raise ValueError("Cannot build SQL without a resolved metric.")

    metrics = load_metrics()
    dimensions = load_dimensions()
    time_semantics = load_time_semantics()
    metric = metrics[plan.metric_name]
    base_source = str(metric["base_source"])

    if metric.get("special_plan") == "invoice_payment_collection_rate":
        return _build_collection_rate_sql(plan, metric, dimensions, time_semantics)

    if metric.get("special_plan") == "invoice_payment_outstanding":
        return _build_outstanding_amount_sql(plan, metric, dimensions, time_semantics)

    date_filter = _build_date_filter(base_source, str(metric.get("date_column", "")), plan.time_phrase, time_semantics, metric)
    where_clauses = list(metric.get("default_filters", []))
    if date_filter["sql"]:
        where_clauses.append(date_filter["sql"])

    dimension_sql = _resolve_dimension_sql(base_source, plan.dimension_name, dimensions)
    select_parts: list[str] = []
    group_by_parts: list[str] = []
    joins: list[str] = []

    if dimension_sql:
        select_parts.extend(dimension_sql["select"])
        group_by_parts.extend(dimension_sql["group_by"])
        joins.extend(dimension_sql["joins"])

    currency_column = metric.get("currency_column")
    if currency_column and plan.metric_name in {"billed_revenue", "collected_revenue", "mrr", "outstanding_amount"}:
        currency_ref = f"base.{currency_column}"
        select_parts.append(f"{currency_ref} as currency")
        group_by_parts.append(currency_ref)

    metric_alias = plan.metric_name
    aggregate_expression = str(metric["aggregate_expression"])

    if plan.intent in {"top_k", "group_by"} and not select_parts:
        select_parts.append("'overall' as result_group")

    select_clause = ",\n    ".join(select_parts + [f"{aggregate_expression} as {metric_alias}"])
    from_clause = f"{base_source} as base"
    join_clause = "\n".join(joins)
    where_clause = " and\n    ".join(where_clauses) if where_clauses else "1 = 1"
    group_by_clause = ""
    if group_by_parts:
        group_by_clause = "\ngroup by\n    " + ",\n    ".join(group_by_parts)

    order_limit_clause = ""
    if plan.intent == "top_k":
        order_limit_clause = f"\norder by {metric_alias} desc\nlimit {plan.limit}"
    elif plan.intent == "group_by":
        order_limit_clause = f"\norder by {metric_alias} desc\nlimit {plan.limit}"

    sql = f"""
select
    {select_clause}
from {from_clause}
{join_clause}
where
    {where_clause}{group_by_clause}{order_limit_clause}
""".strip()

    return {
        "sql": sql,
        "metric": metric,
        "date_range": date_filter,
        "dimension": plan.dimension_name,
        "assumptions": plan.assumptions,
        "warnings": plan.warnings,
    }


def _build_collection_rate_sql(
    plan: SemanticQueryPlan,
    metric: dict[str, Any],
    dimensions: dict[str, dict[str, Any]],
    time_semantics: dict[str, Any],
) -> dict[str, Any]:
    date_filter = _build_date_filter("stripe_invoices", "issued_at", plan.time_phrase, time_semantics, metric, alias="i")
    dimension_sql = _resolve_dimension_sql("stripe_invoices", plan.dimension_name, dimensions, base_alias="i")
    select_parts = []
    group_by_parts = []
    joins = []

    if dimension_sql:
        select_parts.extend(dimension_sql["select"])
        group_by_parts.extend(dimension_sql["group_by"])
        joins.extend(dimension_sql["joins"])

    select_parts.append("i.currency as currency")
    group_by_parts.append("i.currency")

    where_clauses = ["i.status in ('open', 'paid')", "i.invoice_amount > 0"]
    if date_filter["sql"]:
        where_clauses.append(date_filter["sql"])

    group_by_clause = ""
    if group_by_parts:
        group_by_clause = "\ngroup by\n    " + ",\n    ".join(group_by_parts)

    order_limit = ""
    if plan.intent in {"top_k", "group_by"}:
        order_limit = f"\norder by collection_rate desc\nlimit {plan.limit}"

    sql = f"""
with paid_payments_by_invoice as (
    select
        invoice_id,
        currency,
        sum(amount) as collected_payment_amount
    from stripe_payments
    where status = 'paid'
      and amount > 0
      and invoice_id is not null
    group by invoice_id, currency
)
select
    {",\n    ".join(select_parts)},
    sum(i.invoice_amount) as billed_revenue,
    sum(coalesce(p.collected_payment_amount, 0)) as collected_revenue,
    case
        when sum(i.invoice_amount) = 0 then null
        else round(sum(coalesce(p.collected_payment_amount, 0)) * 1.0 / sum(i.invoice_amount), 4)
    end as collection_rate
from stripe_invoices as i
left join paid_payments_by_invoice as p
  on p.invoice_id = i.invoice_id
 and p.currency = i.currency
{chr(10).join(joins)}
where
    {" and".join(chr(10) + "    " + clause for clause in where_clauses).strip()}{group_by_clause}{order_limit}
""".strip()

    return {
        "sql": sql,
        "metric": metric,
        "date_range": date_filter,
        "dimension": plan.dimension_name,
        "assumptions": plan.assumptions,
        "warnings": plan.warnings,
    }


def _build_outstanding_amount_sql(
    plan: SemanticQueryPlan,
    metric: dict[str, Any],
    dimensions: dict[str, dict[str, Any]],
    time_semantics: dict[str, Any],
) -> dict[str, Any]:
    date_filter = _build_date_filter("stripe_invoices", "issued_at", plan.time_phrase, time_semantics, metric, alias="i")
    dimension_sql = _resolve_dimension_sql("stripe_invoices", plan.dimension_name, dimensions, base_alias="i")
    select_parts = []
    group_by_parts = []
    joins = []

    if dimension_sql:
        select_parts.extend(dimension_sql["select"])
        group_by_parts.extend(dimension_sql["group_by"])
        joins.extend(dimension_sql["joins"])

    select_parts.append("i.currency as currency")
    group_by_parts.append("i.currency")

    where_clauses = ["i.status in ('open', 'paid')", "i.invoice_amount > 0"]
    if date_filter["sql"]:
        where_clauses.append(date_filter["sql"])

    group_by_clause = ""
    if group_by_parts:
        group_by_clause = "\ngroup by\n    " + ",\n    ".join(group_by_parts)

    order_limit = ""
    if plan.intent in {"top_k", "group_by"}:
        order_limit = f"\norder by outstanding_amount desc\nlimit {plan.limit}"

    sql = f"""
with paid_payments_by_invoice as (
    select
        invoice_id,
        currency,
        sum(amount) as collected_payment_amount
    from stripe_payments
    where status = 'paid'
      and amount > 0
      and invoice_id is not null
    group by invoice_id, currency
)
select
    {",\n    ".join(select_parts)},
    sum(i.invoice_amount) as billed_revenue,
    sum(coalesce(p.collected_payment_amount, 0)) as collected_revenue,
    sum(i.invoice_amount - coalesce(p.collected_payment_amount, 0)) as outstanding_amount
from stripe_invoices as i
left join paid_payments_by_invoice as p
  on p.invoice_id = i.invoice_id
 and p.currency = i.currency
{chr(10).join(joins)}
where
    {" and".join(chr(10) + "    " + clause for clause in where_clauses).strip()}{group_by_clause}{order_limit}
""".strip()

    return {
        "sql": sql,
        "metric": metric,
        "date_range": date_filter,
        "dimension": plan.dimension_name,
        "assumptions": plan.assumptions,
        "warnings": plan.warnings,
    }


def _resolve_dimension_sql(
    base_source: str,
    dimension_name: str | None,
    dimensions: dict[str, dict[str, Any]],
    base_alias: str = "base",
) -> dict[str, list[str]] | None:
    if not dimension_name:
        return None

    if dimension_name not in dimensions:
        return None

    dimension = dimensions[dimension_name]
    joins: list[str] = []
    select: list[str] = []
    group_by: list[str] = []

    if dimension.get("source") == "metric_base":
        column = str(dimension.get("column"))
        select.append(f"{base_alias}.{column} as {column}")
        group_by.append(f"{base_alias}.{column}")
        return {"select": select, "group_by": group_by, "joins": joins}

    if dimension.get("source") == "dim_customers":
        if base_source != "dim_customers":
            joins.append(f"left join dim_customers as c on c.customer_id = {base_alias}.customer_id")
        else:
            joins.append("")

        if dimension_name == "customer":
            select.extend(["c.customer_id", "c.customer_name"] if base_source != "dim_customers" else ["base.customer_id", "base.customer_name"])
            group_by.extend(["c.customer_id", "c.customer_name"] if base_source != "dim_customers" else ["base.customer_id", "base.customer_name"])
        else:
            column = str(dimension.get("column"))
            alias = "c" if base_source != "dim_customers" else "base"
            select.append(f"{alias}.{column} as {dimension_name}")
            group_by.append(f"{alias}.{column}")
        return {"select": select, "group_by": group_by, "joins": [join for join in joins if join]}

    if dimension.get("source") == "dim_plans":
        if base_source == "fact_subscriptions":
            joins.append("left join dim_plans as pl on pl.plan_id = base.plan_id")
        elif base_source == "stripe_invoices":
            joins.append("left join fact_subscriptions as s on s.subscription_id = base.subscription_id")
            joins.append("left join dim_plans as pl on pl.plan_id = s.plan_id")
        elif base_source == "stripe_payments":
            joins.append("left join dim_plans as pl on pl.plan_id = base.plan_id")
        else:
            joins.append("left join dim_plans as pl on pl.plan_id = base.plan_id")

        if dimension_name == "plan":
            select.extend(["pl.plan_id", "pl.plan_name"])
            group_by.extend(["pl.plan_id", "pl.plan_name"])
        else:
            column = str(dimension.get("column"))
            select.append(f"pl.{column} as {dimension_name}")
            group_by.append(f"pl.{column}")
        return {"select": select, "group_by": group_by, "joins": joins}

    return None


def _build_date_filter(
    table_name: str,
    date_column: str,
    time_phrase: str,
    time_semantics: dict[str, Any],
    metric: dict[str, Any],
    alias: str = "base",
) -> dict[str, Any]:
    if not date_column or time_phrase == "all_time":
        return {"sql": "", "start_date": None, "end_date": None, "time_phrase": time_phrase}

    max_date = _get_max_date(table_name, date_column)
    if not max_date:
        return {"sql": "", "start_date": None, "end_date": None, "time_phrase": time_phrase}

    start_date, end_date = _date_bounds(max_date, time_phrase, time_semantics)
    date_ref = f"date({alias}.{date_column})"

    if metric.get("date_logic") == "active_during_period":
        ended_at_ref = f"date({alias}.ended_at)"
        sql = (
            f"date({alias}.{date_column}) < date('{end_date}') "
            f"and ({alias}.ended_at is null or {ended_at_ref} >= date('{start_date}'))"
        )
    else:
        sql = f"{date_ref} >= date('{start_date}') and {date_ref} < date('{end_date}')"

    return {
        "sql": sql,
        "start_date": start_date,
        "end_date": end_date,
        "time_phrase": time_phrase,
        "anchor_date": max_date.strftime("%Y-%m-%d"),
    }


def _get_max_date(table_name: str, date_column: str) -> datetime | None:
    row = fetch_one(
        f"""
        select max(date({date_column})) as max_date
        from {table_name}
        where {date_column} is not null
        """
    )
    if not row or not row.get("max_date"):
        return None
    return _parse_date(str(row["max_date"]))


def _parse_date(value: str) -> datetime:
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value[:19], date_format)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date value: {value}")


def _date_bounds(anchor_date: datetime, time_phrase: str, time_semantics: dict[str, Any]) -> tuple[str, str]:
    if time_phrase == "last_30_days":
        start = anchor_date - timedelta(days=30)
        end = anchor_date + timedelta(days=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    if time_phrase == "this_month":
        start = anchor_date.replace(day=1)
        end = _add_month(start)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    if time_phrase == "last_month":
        this_month = anchor_date.replace(day=1)
        start = _add_month(this_month, -1)
        end = this_month
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    if time_phrase == "this_quarter":
        start = _quarter_start(anchor_date)
        end = _add_month(start, 3)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    if time_phrase == "last_quarter":
        this_quarter = _quarter_start(anchor_date)
        start = _add_month(this_quarter, -3)
        end = this_quarter
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    start = _add_month(anchor_date.replace(day=1), -1)
    end = anchor_date.replace(day=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _add_month(date_value: datetime, months: int = 1) -> datetime:
    month = date_value.month - 1 + months
    year = date_value.year + month // 12
    month = month % 12 + 1
    return date_value.replace(year=year, month=month, day=1)


def _quarter_start(date_value: datetime) -> datetime:
    quarter_month = ((date_value.month - 1) // 3) * 3 + 1
    return date_value.replace(month=quarter_month, day=1)
