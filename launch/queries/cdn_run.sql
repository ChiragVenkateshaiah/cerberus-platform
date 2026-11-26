-- 17.7: the cache and origin picture per launch session, from the gold mart
-- fct_cdn_run (real CloudFront logs): one row per run with pop = 'ALL', one per
-- POP. {run_ids} is the quoted, comma-separated list of session run ids, each
-- checked by results_pull.py against the same id pattern.
select
    run_id,
    pop,
    requests,
    hits,
    refresh_hits,
    origin_misses,
    cast(round(hit_ratio, 6) as decimal(9, 6)) as hit_ratio,
    cast(round(bytes / 1e6, 3) as decimal(18, 3)) as bytes_mb,
    cast(round(server_ttfb_p50_ms, 3) as decimal(18, 3)) as server_ttfb_p50_ms,
    cast(round(server_ttfb_p99_ms, 3) as decimal(18, 3)) as server_ttfb_p99_ms,
    logs_status
from cerberus_platform.fct_cdn_run
where run_id in ({run_ids})
order by run_id, pop
