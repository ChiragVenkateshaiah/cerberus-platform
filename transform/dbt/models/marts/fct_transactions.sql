-- Latest-event-wins per transaction_id, same resolution 1.7's Python/pandas
-- transform uses for payments_current -- expressed here in SQL, emitting
-- merchant_id/customer_id as foreign keys into dim_merchants/dim_customers
-- instead of embedding name/category/email inline. This is the fact/
-- dimension split ADR 0003 assigned to 1.9.
with ranked as (
    select
        *,
        row_number() over (
            partition by transaction_id
            order by event_timestamp desc
        ) as rn
    from {{ source('cerberus_platform', 'payments_events') }}
)

select
    transaction_id,
    event_type as status,
    event_timestamp as last_event_at,
    amount,
    currency,
    merchant_id,
    customer_id,
    payment_method_type,
    payment_method_brand,
    payment_method_last4,
    payment_method_token
from ranked
where rn = 1
