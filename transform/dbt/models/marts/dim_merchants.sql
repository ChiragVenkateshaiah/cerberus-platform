-- Per ADR 0003 the merchant roster is fixed and reused across events, not
-- regenerated per event -- there's no variation to resolve, so no
-- latest-wins logic is needed here (unlike fct_transactions).
select distinct
    merchant_id,
    merchant_name,
    merchant_category
from {{ source('cerberus_platform', 'payments_events') }}
