# PipeForge Subscription Finance Test Cases

These prompts are designed to validate the upgraded 5-table demo database:

- `dim_customers`
- `dim_plans`
- `fact_subscriptions`
- `stripe_invoices`
- `stripe_payments`

Use these as manual regression test cases after reseeding the database.

---

## Test Case 1 — Single-source invoice revenue baseline

### Prompt

```text
Build a trusted monthly invoice revenue dataset from Stripe invoices for a billing dashboard. We need invoice revenue by customer segment and currency.
```

### Expected routing

```text
scope: single_source
selected_source: stripe_invoices
```

### Expected behavior

The system should use only `stripe_invoices` and should not trigger multi-source relationship validation.

### Expected artifacts

```text
source_profile.md
data_quality_report.md
business_rules.yml
business_rules.md
stg_stripe__invoices.sql
int_invoices__billing_rules.sql
mart_billing__monthly_invoice_revenue_by_segment.sql
schema.yml
custom_tests/test_monthly_invoice_revenue_not_null.sql
pipeline_summary.md
```

### Expected decisions

Likely business questions include:

```text
How should missing invoice discount_amount values be handled?
How should uncollectible invoices be handled?
How should multi-currency invoice revenue be reported?
```

---

## Test Case 2 — Invoice-payment reconciliation

### Prompt

```text
Reconcile billed invoice revenue with collected payments. We need to compare invoices and payments, identify invoices without matching payments, and report collected revenue by month.
```

### Expected routing

```text
scope: multi_source
selected_data_product: stripe_billing_reconciliation
sources:
  - stripe_invoices
  - stripe_payments
relationships:
  - invoices_to_payments_by_invoice_id
```

### Expected behavior

The system should validate invoice-payment matching through `invoice_id`, not by raw `customer_id`.

### Expected findings

Possible relationship findings include:

```text
duplicate stripe_invoices.invoice_id values
invoices without matching payments
payments without matching invoices
payments with null invoice_id
partial payments
overpayments
invoice/payment currency mismatch
```

### Expected artifacts

```text
source_profile.md
data_quality_report.md
relationship_profile.md
join_quality_report.md
join_plan.md
business_rules.yml
business_rules.md
stg_stripe__invoices.sql
stg_stripe__payments.sql
int_billing__invoice_payment_reconciliation.sql
mart_billing__monthly_reconciliation.sql
schema.yml
custom_tests/test_no_duplicate_invoice_reconciliation_rows.sql
custom_tests/test_reconciliation_difference_not_null.sql
pipeline_summary.md
```

---

## Test Case 3 — Revenue 360 across dimensions and facts

### Prompt

```text
Create a revenue 360 mart that combines customers, subscriptions, plans, invoices, and payments. We need monthly billed revenue, collected revenue, MRR, customer segment, country, industry, and product family.
```

### Expected routing

```text
scope: multi_source
selected_data_product: subscription_revenue_360
sources:
  - dim_customers
  - dim_plans
  - fact_subscriptions
  - stripe_invoices
  - stripe_payments
relationships:
  - customers_to_subscriptions
  - plans_to_subscriptions
  - subscriptions_to_invoices
  - invoices_to_payments_by_invoice_id
```

### Expected behavior

The system should build a multi-hop join plan:

```text
dim_customers -> fact_subscriptions
dim_plans -> fact_subscriptions
fact_subscriptions -> stripe_invoices
stripe_invoices -> stripe_payments
```

### Expected final mart

```text
mart_subscription__revenue_360_monthly
```

### Expected artifacts

```text
source_profile.md
data_quality_report.md
relationship_profile.md
join_quality_report.md
join_plan.md
business_rules.yml
business_rules.md
stg_demo__customers.sql
stg_demo__plans.sql
stg_demo__subscriptions.sql
stg_stripe__invoices.sql
stg_stripe__payments.sql
int_subscription__revenue_360.sql
mart_subscription__revenue_360_monthly.sql
schema.yml
custom_tests/test_revenue_360_grain_unique.sql
custom_tests/test_revenue_360_metrics_not_null.sql
pipeline_summary.md
```

### Expected decisions

Likely business questions include:

```text
How should subscriptions without invoices be handled?
How should multi-currency revenue be reported?
How should payments without a matching invoice be handled?
```

---

## Test Case 4 — Collection health / accounts receivable analytics

### Prompt

```text
Build a collection health dashboard. I want to find overdue invoices, unpaid invoices, partial payments, overpayments, and payment collection rate by customer segment and country.
```

### Expected routing

```text
scope: multi_source
selected_data_product: subscription_collection_health
sources:
  - dim_customers
  - stripe_invoices
  - stripe_payments
relationships:
  - customers_to_invoices
  - invoices_to_payments_by_invoice_id
```

### Expected behavior

The system should combine customer attributes with invoice/payment coverage to build collection metrics.

### Expected final mart

```text
mart_billing__collection_health_monthly
```

### Expected metrics

```text
billed_amount
collected_payment_amount
outstanding_amount
collection_rate
overdue_invoice_count
unpaid_invoice_count
partial_payment_count
overpayment_count
```

### Expected decisions

Likely business questions include:

```text
How should overdue open invoices be classified?
How should partial payments and overpayments be represented?
```

---

## Test Case 5 — Ambiguous executive dashboard request

### Prompt

```text
Join all available tables and create the best possible executive revenue dashboard.
```

### Expected routing

```text
scope: multi_source or ambiguous
```

### Expected behavior

The system should not invent unknown relationships. It should either:

```text
1. Select the closest data product if confidence is high, likely subscription_revenue_360; or
2. Ask for clarification in a future version.
```

### Expected safety behavior

The output should clearly state selected sources and relationships. It should not join tables that are not defined in `relationships.yml`.

### Expected artifact behavior

If it routes to `subscription_revenue_360`, expected final mart:

```text
mart_subscription__revenue_360_monthly
```

If it cannot confidently route, expected behavior is a clear failure/clarification message rather than hallucinated SQL.
