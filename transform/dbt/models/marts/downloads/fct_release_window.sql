-- 17.5: per (run_id, region, minute) from T-60 min to T+6 h, where T is the
-- region's local midnight of release day. region_nn is 1..24 and the zone is
-- UTC(region_nn - 12) (the generator's offset_hours), so T in UTC is the
-- release_utc variable minus that many hours. The 24 offsets come from a
-- Jinja range, not a table.
with regions as (
    {% for n in range(1, 25) %}
        select
            {{ n }} as region_nn,
            'region_{{ '%02d' % n }}' as region,
            date_add(
                'hour', -({{ n }} - 12), timestamp '{{ var("release_utc") }}'
            ) as release_at
        {% if not loop.last %}
            union all
        {% endif %}
    {% endfor %}
),

events as (
    select
        e.run_id,
        e.region,
        e.client_id,
        e.event_type,
        e.http_status,
        e.bytes,
        r.release_at,
        date_trunc('minute', cast(e.occurred_at as timestamp(6))) as minute_at
    from {{ source('cerberus_downloads', 'download_events') }} as e
    inner join regions as r on e.region = r.region
    where
        cast(e.occurred_at as timestamp(6))
        >= date_add('minute', -60, r.release_at)
        and cast(e.occurred_at as timestamp(6))
        < date_add('hour', 6, r.release_at)
)

select
    run_id,
    region,
    minute_at,
    date_diff('minute', max(release_at), minute_at) as minutes_from_release,
    count_if(event_type = 'license_requested' and http_status = 200)
        as license_requests,
    count_if(event_type = 'license_requested' and http_status = 403)
        as early_license_denials,
    count_if(event_type = 'license_granted') as licenses_granted,
    count(distinct case when event_type = 'chunk_completed' then client_id end)
        as clients_with_chunk,
    sum(case when event_type = 'chunk_completed' then bytes else 0 end)
        as chunk_bytes,
    count_if(event_type = 'stalled') as stalls,
    count_if(event_type = 'install_completed') as installs
from events
group by run_id, region, minute_at
