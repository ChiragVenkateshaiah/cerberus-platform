-- 17.7: edge results per run, POP and URI class (build, patch, other), from the
-- gold mart fct_cdn_requests. Hit ratio is request-based: hits over hits, refresh
-- hits and misses, the same rule as fct_cdn_run.
select
    run_id,
    pop,
    case
        when uri_stem like '/build/%' then 'build'
        when uri_stem like '/patch/%' then 'patch'
        else 'other'
    end as uri_class,
    count(*) as requests,
    count_if(edge_result_type = 'Hit') as hits,
    count_if(edge_result_type = 'RefreshHit') as refresh_hits,
    count_if(edge_result_type = 'Miss') as origin_misses,
    cast(round(sum(bytes) / 1e6, 3) as decimal(18, 3)) as bytes_mb
from cerberus_platform.fct_cdn_requests
where run_id in ({run_ids})
group by
    run_id,
    pop,
    case
        when uri_stem like '/build/%' then 'build'
        when uri_stem like '/patch/%' then 'patch'
        else 'other'
    end
order by run_id, pop, uri_class
