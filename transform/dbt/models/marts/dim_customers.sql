-- Same reasoning as dim_merchants: fixed roster, no latest-wins needed.
select distinct
    customer_id,
    customer_name,
    customer_email
from {{ source('cerberus_platform', 'payments_events') }}
