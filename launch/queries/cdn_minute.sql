-- 17.7: edge requests and MB per run and minute, over every POP, from the gold
-- mart fct_cdn_requests. The render turns MB per minute into Gbps.
select
    run_id,
    cast(date_trunc('minute', requested_at) as varchar) as minute_at,
    count(*) as requests,
    cast(round(sum(bytes) / 1e6, 3) as decimal(18, 3)) as bytes_mb
from cerberus_platform.fct_cdn_requests
where run_id in ({run_ids})
group by run_id, date_trunc('minute', requested_at)
order by run_id, minute_at
