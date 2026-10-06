-- Cerberus 1.10 demo query -- the MVP definition-of-done artifact from
-- docs/plan.md: "a reviewer runs a single Athena query against the gold
-- table and gets a result." Joins 1.9's fct_transactions against
-- dim_merchants rather than a plain count -- it's the actual payoff of
-- doing the fact/dimension split (ADR 0003) instead of querying
-- payments_current directly.
--
-- Grouped by currency too: payments arrive in USD, EUR and GBP, and a
-- single sum across them would add unlike units (found by 2026-10-06's
-- data-quality pass). One row per merchant per currency.
select
    m.merchant_name,
    m.merchant_category,
    f.currency,
    count(*) as settled_transactions,
    round(sum(f.amount), 2) as total_settled_amount
from cerberus_platform.fct_transactions f
join cerberus_platform.dim_merchants m
    on f.merchant_id = m.merchant_id
where f.status = 'settled'
group by m.merchant_name, m.merchant_category, f.currency
order by f.currency, total_settled_amount desc
