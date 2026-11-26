-- 17.7: edge results per sub-run (d-0 cold, d-1 warm, ...), from the gold mart
-- fct_cdn_requests. {windows} is the list of sub-run windows, one row each:
-- ('session run id', 'sub-run name', start_ms, end_ms). results_pull.py builds it
-- from the window.json files the instance wrote, after checking each run id and
-- name against a pattern and each time as a whole number of epoch milliseconds.
-- The time is added to the epoch as a plain timestamp (UTC), the same clock as
-- requested_at. Hit ratio is request-based, the same rule as cdn_class.
with windows (run_id, sub_run, start_ms, end_ms) as (
    values {windows}
)
select
    w.run_id,
    w.sub_run,
    count(r.run_id) as requests,
    count_if(r.edge_result_type = 'Hit') as hits,
    count_if(r.edge_result_type = 'RefreshHit') as refresh_hits,
    count_if(r.edge_result_type = 'Miss') as origin_misses,
    cast(round(
        cast(count_if(r.edge_result_type = 'Hit') as double)
        / nullif(count_if(r.edge_result_type in ('Hit', 'RefreshHit', 'Miss')), 0),
        6
    ) as decimal(9, 6)) as hit_ratio
from windows as w
left join cerberus_platform.fct_cdn_requests as r
    on r.run_id = w.run_id
    and r.requested_at >= date_add('millisecond', w.start_ms, timestamp '1970-01-01 00:00:00')
    and r.requested_at <= date_add('millisecond', w.end_ms, timestamp '1970-01-01 00:00:00')
group by w.run_id, w.sub_run
order by w.run_id, w.sub_run
