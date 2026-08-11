-- Latest-event-wins per transaction_id, same resolution 1.7's Python/pandas
-- transform uses for payments_current -- expressed here in SQL, emitting
-- merchant_id/customer_id as foreign keys into dim_merchants/dim_customers
-- instead of embedding name/category/email inline. This is the fact/
-- dimension split ADR 0003 assigned to 1.9.
with ranked as (
    select
        *,
        -- event_timestamp alone can tie: generate_payments.py clamps every
        -- event to min(ts, now), so a settled event and a later refund can
        -- both land on "now" with identical timestamps. This fixed
        -- lifecycle order breaks the tie the same way promote_payments.py's
        -- EVENT_TYPE_RANK does (settled/failed share a rank -- only one
        -- ever occurs per transaction).
        row_number() over (
            partition by transaction_id
            order by
                event_timestamp desc,
                case event_type
                    when 'refunded' then 3
                    when 'settled' then 2
                    when 'failed' then 2
                    when 'authorized' then 1
                    when 'created' then 0
                end desc
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
