-- Latest-event-wins per transaction_id, same resolution 1.7's Python/pandas
-- transform uses for payments_current -- expressed here in SQL, emitting
-- merchant_id/customer_id as foreign keys into dim_merchants/dim_customers
-- instead of embedding name/category/email inline. This is the fact/
-- dimension split ADR 0003 assigned to 1.9.
{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='transaction_id',
    )
}}

-- 8.5 (ADR 0017): incremental. A run recomputes latest-event-wins only for
-- transactions that got a new silver event since the last run -- found by
-- silver's loaded_at (one value per silver job run) against the newest
-- silver_loaded_at already in gold -- but over ALL of each such
-- transaction's events, because a refund can land days after its
-- settlement. The merge on transaction_id then replaces those rows. Without
-- an existing table (the first run, or --full-refresh) it is the full
-- rebuild it always was.

with events as (
    select * from {{ source('cerberus_platform', 'payments_events') }}
),

{% if is_incremental() %}
    touched as (
        select distinct e.transaction_id
        from events as e
        where
            cast(e.loaded_at as timestamp(6))
            > (select max(g.silver_loaded_at) from {{ this }} as g)
    ),
{% endif %}

ranked as (
    select
        events.*,
        max(events.loaded_at)
            over (partition by events.transaction_id)
            as latest_loaded_at,
        row_number() over (
            partition by events.transaction_id
            order by
                events.event_timestamp desc,
                case events.event_type
                    when 'refunded' then 3
                    when 'settled' then 2
                    when 'failed' then 2
                    when 'authorized' then 1
                    when 'created' then 0
                end desc
        ) as rn
    from events
    {% if is_incremental() %}
        where
            events.transaction_id in (
                select t.transaction_id from touched as t
            )
    {% endif %}
)

select
    transaction_id,
    event_type as status,
    -- Silver is Iceberg with timestamptz (Spark's timestamps); Athena's
    -- Iceberg tables store timestamp(6) without a zone. The values are UTC,
    -- so the cast keeps the same UTC wall-clock time.
    cast(event_timestamp as timestamp(6)) as last_event_at,
    amount,
    currency,
    merchant_id,
    customer_id,
    payment_method_type,
    payment_method_brand,
    payment_method_last4,
    payment_method_token,
    -- When silver last loaded an event of this transaction: the next run's
    -- cutoff for "new since gold was built".
    cast(latest_loaded_at as timestamp(6)) as silver_loaded_at
from ranked
where rn = 1
