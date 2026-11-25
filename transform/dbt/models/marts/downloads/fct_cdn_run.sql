-- 17.5: the cache and origin picture of a run, from the real logs: one row for
-- the run (pop = 'ALL') and one per POP. grouping sets does both in one scan.
--
-- Result types are CloudFront's x-edge-result-type names (Hit, RefreshHit,
-- Miss, ...; from the AWS log reference, unverified in this repo).
-- hit_ratio = Hit / (Hit + RefreshHit + Miss): the requests that looked in the
-- cache. origin_misses = Miss.
--
-- server_ttfb_* is the edge's own time-to-first-byte from the logs, in ms. It
-- is not the client TTFB k6 measures and the two are never mixed or compared
-- as one number (ADR 0030).
select
    run_id,
    coalesce(pop, 'ALL') as pop,
    count(*) as requests,
    count_if(edge_result_type = 'Hit') as hits,
    count_if(edge_result_type = 'RefreshHit') as refresh_hits,
    count_if(edge_result_type = 'Miss') as origin_misses,
    cast(count_if(edge_result_type = 'Hit') as double)
    / nullif(
        count_if(edge_result_type in ('Hit', 'RefreshHit', 'Miss')), 0
    ) as hit_ratio,
    sum(bytes) as bytes,
    approx_percentile(server_ttfb_s, 0.5) * 1000 as server_ttfb_p50_ms,
    approx_percentile(server_ttfb_s, 0.99) * 1000 as server_ttfb_p99_ms
from {{ ref('fct_cdn_requests') }}
group by grouping sets ((run_id), (run_id, pop))
