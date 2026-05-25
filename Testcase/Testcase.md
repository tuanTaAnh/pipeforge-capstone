# PipeForge Testcases

This document contains 6 main testcases for validating the current PipeForge demo flow.

Coverage summary:

1. Out-of-scope request
2. Direct Analytics — clear metric/ranking query
3. Direct Analytics — ambiguous metric requiring `ask_user`
4. Data Product / Pipeline Generation — simple pipeline, no clarification
5. Data Product / Pipeline Generation — reconciliation / collection gap pipeline
6. Default UI Testcase — trusted monthly revenue dataset with refund/discount business-rule clarification

---

## Testcase 1 — Out of scope

### Input

```text
Who won the football match yesterday?
```

### Expected route

```text
request_type = out_of_scope
clarification_required = false
```

### Expected behavior

The system should recognize that the question is unrelated to the available PipeForge demo data.

It should not generate SQL.

It should not generate pipeline/data product artifacts.

It should not ask the user for clarification.

### Pass criteria

```text
PASS: request_type = out_of_scope
PASS: clarification_required = false
PASS: selected_sources = []
PASS: no analytics_query.sql is generated
PASS: no OpenHands artifact generation is triggered
PASS: final answer explains that the request is outside the available subscription/revenue dataset
```

---

## Testcase 2 — Direct Analytics: highest MRR customer

### Input

```text
Who is the customer with highest MRR?
```

### Expected route

```text
request_type = direct_analytics
clarification_required = false
```

### Expected selected sources

```text
fact_subscriptions
dim_customers
```

### Expected SQL logic

```sql
SELECT
  c.customer_id,
  c.customer_name,
  c.customer_segment,
  SUM(s.mrr_amount) AS total_mrr
FROM fact_subscriptions AS s
JOIN dim_customers AS c
  ON c.customer_id = s.customer_id
GROUP BY
  c.customer_id,
  c.customer_name,
  c.customer_segment
ORDER BY total_mrr DESC
LIMIT 1;
```

### Expected artifacts

```text
semantic_query_plan.json
analytics_query.sql
analytics_result.json
analytics_answer.md
```

### Pass criteria

```text
PASS: no ask_user event
PASS: uses fact_subscriptions.mrr_amount
PASS: joins dim_customers by customer_id
PASS: returns exactly one top customer
PASS: does not use unavailable columns such as currency, status, or payment_amount
PASS: does not route to data_product_generation
```

---

## Testcase 3 — Direct Analytics: ambiguous revenue definition requiring ask_user

### Input

```text
Show me revenue for May 2026.
```

### Expected route before user answer

```text
request_type = direct_analytics or clarification
clarification_required = true
```

### Expected ask_user question

```text
Which revenue definition should I use for May 2026?
```

### Expected options

```text
1. Billed revenue from invoices
2. Collected revenue from successful payments
3. Gross MRR from subscriptions
4. Net MRR after discounts and refunds
```

### Test answer

```text
Use billed revenue from invoices.
```

### Expected route after answer

```text
request_type = direct_analytics
clarification_required = false
selected_sources = ["stripe_invoices"]
selected_metrics = ["billed_revenue"]
selected_dimensions = ["invoice_month"]
```

### Expected SQL logic

```sql
SELECT
  SUM(invoice_amount) AS billed_revenue
FROM stripe_invoices
WHERE invoice_month = '2026-05';
```

### Pass criteria

```text
PASS: asks user because "revenue" is ambiguous
PASS: does not guess revenue definition silently
PASS: after user answer, routes to direct_analytics
PASS: uses stripe_invoices.invoice_amount
PASS: filters by invoice_month = '2026-05'
PASS: does not use issued_at, date(), currency, status, or payment_amount
```

---

## Testcase 4 — Pipeline Generation: simple monthly billed revenue pipeline

### Input

```text
Create a monthly billed revenue pipeline from Stripe invoices for the analytics team.
```

### Expected route

```text
request_type = data_product_generation
clarification_required = false
```

### Expected selected sources

```text
stripe_invoices
```

### Expected selected metrics and dimensions

```text
selected_metrics = ["billed_revenue"]
selected_dimensions = ["invoice_month"]
```

### Expected artifacts

At minimum, the system should generate a small data product package such as:

```text
artifact_plan.json
source_profile.md
data_quality_report.md
business_rules.yml or business_rules.md if needed
stg_stripe__invoices.sql
mart_billing__monthly_invoice_revenue.sql or equivalent monthly billed revenue mart
schema.yml
pipeline_summary.md
```

### Expected mart logic

```sql
SELECT
  invoice_month,
  SUM(invoice_amount) AS billed_revenue
FROM {{ ref('stg_stripe__invoices') }}
GROUP BY invoice_month;
```

### Pass criteria

```text
PASS: routes to data_product_generation
PASS: does not ask user because billed revenue is clear
PASS: uses stripe_invoices.invoice_month as a text month key
PASS: does not parse invoice_month with date(), datetime(), or strftime()
PASS: uses stripe_invoices.invoice_amount
PASS: generated artifacts validate successfully
PASS: pipeline execution creates a monthly billed revenue output table
```

---

## Testcase 5 — Pipeline Generation: billed vs collected revenue reconciliation

### Input

```text
Build a pipeline that compares monthly billed revenue from invoices with collected revenue from successful payments, so finance can review collection gaps.
```

### Expected route

```text
request_type = data_product_generation
clarification_required = false
```

### Expected selected sources

```text
stripe_invoices
stripe_payments
```

### Expected selected metrics

```text
billed_revenue
collected_revenue
```

### Expected data product

```text
selected_data_product = stripe_billing_reconciliation or subscription_collection_health
```

The exact selected data product can vary depending on the metadata contract, but it should clearly represent billing reconciliation or collection health.

### Expected artifacts

At minimum:

```text
artifact_plan.json
source_profile.md
data_quality_report.md
relationship_profile.md or join_quality_report.md
stg_stripe__invoices.sql
stg_stripe__payments.sql
intermediate reconciliation model
final mart comparing billed_revenue and collected_revenue
schema.yml
pipeline_summary.md
```

### Expected mart fields

```text
revenue_month or invoice_month
billed_revenue
collected_revenue
collection_gap
```

### Expected business logic

```text
billed_revenue = SUM(stripe_invoices.invoice_amount)
collected_revenue = SUM(stripe_payments.successful_amount)
collection_gap = billed_revenue - collected_revenue
```

### Pass criteria

```text
PASS: routes to data_product_generation
PASS: does not ask user if billed vs collected semantics are clear
PASS: uses invoice_id relationship between invoices and payments where needed
PASS: uses successful_amount, not payment_amount
PASS: does not use currency/status columns
PASS: does not create calendar/date spine tables unless explicitly available
PASS: does not parse invoice_month/payment_month into NULL
PASS: generated artifacts validate successfully
PASS: pipeline execution produces a reconciliation/collection gap output
```

---

## Testcase 6 — Default UI Testcase: trusted monthly revenue data product with refund/discount decision

### Input

```text
Our finance team needs a trusted monthly revenue dataset from Stripe for a board dashboard. We need MRR by customer segment, but we are not sure how refunds and discounts should be handled. Can you prepare this as a data product draft for our analytics team?
```

### Expected route before user answer

```text
request_type = data_product_generation
clarification_required = true
selected_data_product = subscription_revenue_360
```

### Expected selected sources

```text
dim_customers
dim_plans
fact_subscriptions
stripe_invoices
stripe_payments
```

### Expected selected metrics

```text
gross_mrr
mrr
discount_amount
refund_amount
net_mrr
billed_revenue
collected_revenue
```

### Expected selected dimensions

```text
invoice_month
customer_segment
```

### Expected ask_user question

```text
How should refunds and discounts be handled in the monthly revenue data product?
```

### Expected options

```text
1. Report gross MRR only and show adjustments separately
2. Report net MRR after discounts and refunds
3. Report both gross MRR and net MRR with adjustment breakdown
```

### Test answer

```text
Report both gross MRR and net MRR with adjustment breakdown.
```

### Expected route after user answer

```text
request_type = data_product_generation
clarification_required = false
selected_data_product = subscription_revenue_360
```

### Expected final artifacts

```text
source_profile.md
data_quality_report.md
relationship_profile.md
join_quality_report.md
business_rules.yml
business_rules.md
artifact_plan.json
stg_demo__customers.sql
stg_demo__plans.sql
stg_demo__subscriptions.sql
stg_stripe__invoices.sql
stg_stripe__payments.sql
int_subscription__mrr_adjustments.sql
mart_subscription__revenue_360_monthly.sql
schema.yml
custom_tests/test_revenue_360_metrics_not_null.sql
pipeline_summary.md
```

### Expected final mart grain

```text
invoice_month or revenue_month
customer_segment
```

### Expected final mart fields

```text
invoice_month or revenue_month
customer_segment
gross_mrr
discount_amount
refund_amount
net_mrr
```

### Expected metric logic

```text
gross_mrr = SUM(fact_subscriptions.mrr_amount)
discount_amount = SUM(COALESCE(stripe_invoices.discount_amount, 0))
refund_amount = SUM(COALESCE(stripe_payments.refund_amount, 0))
net_mrr = gross_mrr - discount_amount - refund_amount
```

### Pass criteria

```text
PASS: asks user before generating the final data product
PASS: records user decision in business_rules.yml / business_rules.md
PASS: generated SQL uses only current schema columns
PASS: does not use currency, status, payment_amount, country, monthly_price, issued_at, paid_at, or refunded_at
PASS: invoice_month/payment_month are preserved as YYYY-MM text keys or normalized with substr(column, 1, 7)
PASS: no date(), datetime(), or strftime() parsing creates NULL month values
PASS: artifact validation passes
PASS: targeted repair is only used if validation fails
PASS: final pipeline execution succeeds
PASS: final mart contains non-null month values and expected revenue metrics
```

---

## Final coverage checklist

```text
Out-of-scope handling: Testcase 1
Direct analytics clear route: Testcase 2
Direct analytics ask_user: Testcase 3
Simple pipeline generation: Testcase 4
Reconciliation / collection gap pipeline: Testcase 5
Default UI data product + business-rule ask_user: Testcase 6
```

Expected ratio:

```text
1 out-of-scope case
2 direct analytics cases
3 data product / pipeline cases
2 ask_user cases
```
