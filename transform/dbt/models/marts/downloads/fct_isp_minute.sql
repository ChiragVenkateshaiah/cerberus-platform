-- 17.5: per (run_id, isp, minute), how many consoles were pulling bytes, the
-- Gbps that implies, and how many of them stalled.
--
-- Modelled, not measured: a chunk_completed or patch_completed event ends at
-- occurred_at and lasted duration_ms, so its bytes are spread evenly over
-- that span, minute by minute. modelled_gbps is the bytes of the minute x 8 /
-- 60 s / 1e9. A client is active in a minute when a span covers it, or when
-- it stalled in it (a stall comes before its chunk starts). A transfer with
-- duration_ms = 0 is dropped (it has no span to spread bytes over).
with transfers as (
    select
        run_id,
        isp,
        client_id,
        bytes,
        duration_ms,
        cast(occurred_at as timestamp(6)) as ended_at,
        date_add(
            'millisecond', -duration_ms, cast(occurred_at as timestamp(6))
        ) as started_at
    from {{ source('cerberus_downloads', 'download_events') }}
    where
        event_type in ('chunk_completed', 'patch_completed')
        and duration_ms > 0
),

spans as (
    select
        t.run_id,
        t.isp,
        t.client_id,
        m.minute_start as minute_at,
        cast(0 as bigint) as stalled,
        t.bytes
        * date_diff(
            'millisecond',
            greatest(t.started_at, m.minute_start),
            least(t.ended_at, date_add('minute', 1, m.minute_start))
        )
        / cast(nullif(t.duration_ms, 0) as double) as bytes_in_minute
    from transfers as t
    cross join
        unnest(
            sequence(
                date_trunc('minute', t.started_at),
                date_trunc('minute', t.ended_at),
                interval '1' minute
            )
        ) as m (minute_start)
    -- A transfer that ends exactly on a minute boundary has no time in the
    -- minute that starts there: drop that zero-byte span.
    where m.minute_start < t.ended_at
),

stalls as (
    select
        run_id,
        isp,
        client_id,
        date_trunc('minute', cast(occurred_at as timestamp(6))) as minute_at,
        cast(1 as bigint) as stalled,
        cast(0 as double) as bytes_in_minute
    from {{ source('cerberus_downloads', 'download_events') }}
    where event_type = 'stalled'
),

combined as (
    select * from spans
    union all
    select * from stalls
)

select
    run_id,
    isp,
    minute_at,
    count(distinct client_id) as active_clients,
    count(distinct case when stalled = 1 then client_id end) as stalled_clients,
    sum(bytes_in_minute) * 8 / 60 / 1e9 as modelled_gbps,
    cast(count(distinct case when stalled = 1 then client_id end) as double)
    / count(distinct client_id) as stall_rate
from combined
group by run_id, isp, minute_at
