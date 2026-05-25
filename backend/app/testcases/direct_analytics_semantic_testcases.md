# Direct Analytics Q&A Semantic Testcases

These testcases validate the Direct Analytics Q&A mode introduced on top of the semantic mapping layer.

The expected behavior is different from data product generation:

- Direct analytics questions should generate and execute safe SQL.
- The system should return a direct answer in chat.
- The system should create reviewable artifacts:
  - `semantic_query_plan.json`
  - `analytics_query.sql`
  - `analytics_result.json`
  - `analytics_answer.md`
- Ambiguous terms should trigger a clarification question instead of silently guessing.

---

## Test Case 1 — Highest billed revenue customer

### Prompt

```text
Which customer generated the highest billed revenue last month?
```

### Expected routing

```text
Direct Analytics Q&A mode
```

### Expected semantic mapping

```text
Metric: billed_revenue
Source: stripe_invoices
Amount column: invoice_amount
Date column: issued_at
Dimension: customer
Join: stripe_invoices.customer_id -> dim_customers.customer_id
Time phrase: last_month
```

### Expected behavior

The system should not ask a clarification question because `billed revenue` is explicit.

The system should execute SQL and return the top customer by `sum(stripe_invoices.invoice_amount)` for the previous calendar month relative to the latest `issued_at` in the dataset.

### Expected artifacts

```text
semantic_query_plan.json
analytics_query.sql
analytics_result.json
analytics_answer.md
```

---

## Test Case 2 — Ambiguous revenue metric

### Prompt

```text
Which customer generated the highest revenue last month?
```

### Expected routing

```text
Direct Analytics Q&A mode
```

### Expected behavior

The system should ask a clarification question because `revenue` is ambiguous.

Expected options:

```text
Billed Revenue
Collected Revenue
Monthly Recurring Revenue
```

After the user selects one option, the system should execute SQL using the selected metric and return a direct answer.

---

## Test Case 3 — Highest collected revenue customer

### Prompt

```text
Which customer generated the highest collected revenue last month?
```

### Expected semantic mapping

```text
Metric: collected_revenue
Source: stripe_payments
Amount column: amount
Date column: paid_at
Dimension: customer
Join: stripe_payments.customer_id -> dim_customers.customer_id
Filters: status = 'paid', amount > 0, paid_at is not null
```

### Expected behavior

The system should execute SQL and return the top customer by collected paid payments.

---

## Test Case 4 — Total billed revenue

### Prompt

```text
What was total billed revenue last month?
```

### Expected semantic mapping

```text
Metric: billed_revenue
Source: stripe_invoices
Amount column: invoice_amount
Date column: issued_at
Time phrase: last_month
```

### Expected behavior

The system should execute SQL and return total billed revenue. Because no FX conversion exists, results may be grouped by currency.

---

## Test Case 5 — Highest unpaid invoice amount by segment

### Prompt

```text
Which segment has the highest unpaid invoice amount last month?
```

### Expected semantic mapping

```text
Metric: outstanding_amount
Sources: stripe_invoices + stripe_payments + dim_customers
Join path:
  stripe_invoices.invoice_id -> stripe_payments.invoice_id
  stripe_invoices.customer_id -> dim_customers.customer_id
Dimension: customer_segment
```

### Expected behavior

The system should calculate outstanding amount as invoice amount minus paid payments matched by invoice_id and return the top customer segment.

---

## Test Case 6 — Highest MRR product family

### Prompt

```text
Which product family has the highest MRR last month?
```

### Expected semantic mapping

```text
Metric: mrr
Source: fact_subscriptions
Dimension: product_family
Join: fact_subscriptions.plan_id -> dim_plans.plan_id
Time logic: subscription active during the selected period
```

### Expected behavior

The system should execute SQL and return the product family with the highest MRR.

---

## Test Case 7 — Data product generation should still route correctly

### Prompt

```text
Create a revenue 360 mart that combines customers, subscriptions, plans, invoices, and payments. We need monthly billed revenue, collected revenue, MRR, customer segment, country, industry, and product family.
```

### Expected routing

```text
Data product generation mode
```

### Expected data product

```text
subscription_revenue_360
```

### Expected behavior

This should not be treated as Direct Analytics Q&A because it asks to create a mart/data product.
