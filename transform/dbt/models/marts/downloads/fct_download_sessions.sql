-- 17.5: one row per (run_id, client_id), the milestone times of one console's
-- download of the title. A mart is rebuilt in full, like the payments dims:
-- the exercise builds it once after silver is final.
--
-- Bytes: chunk_completed and patch_completed carry the bytes moved.
-- preload_completed repeats the whole title and stalled carries a partial
-- chunk, so neither is added. The early 403 licence request of a few
-- pre-loaders is counted apart from the real ask (http_status 200).
with events as (
    select
        run_id,
        client_id,
        platform,
        region,
        isp,
        event_type,
        http_status,
        bytes,
        cast(occurred_at as timestamp(6)) as occurred_at
    from {{ source('cerberus_downloads', 'download_events') }}
),

sessions as (
    select
        run_id,
        client_id,
        min(platform) as platform,
        min(region) as region,
        min(isp) as isp,
        min(occurred_at) as first_event_at,
        max(occurred_at) as last_event_at,
        min(case when event_type = 'preload_started' then occurred_at end)
            as preload_started_at,
        min(case when event_type = 'preload_completed' then occurred_at end)
            as preload_completed_at,
        min(
            case
                when event_type = 'license_requested' and http_status = 200
                    then occurred_at
            end
        ) as license_requested_at,
        min(case when event_type = 'license_granted' then occurred_at end)
            as license_granted_at,
        min(case when event_type = 'patch_started' then occurred_at end)
            as patch_started_at,
        min(case when event_type = 'patch_completed' then occurred_at end)
            as patch_completed_at,
        min(case when event_type = 'install_completed' then occurred_at end)
            as install_completed_at,
        min(case when event_type = 'abandoned' then occurred_at end)
            as abandoned_at,
        sum(
            case
                when event_type in ('chunk_completed', 'patch_completed')
                    then bytes
                else 0
            end
        ) as bytes_downloaded,
        count_if(event_type = 'chunk_completed') as chunks_completed,
        count_if(event_type = 'stalled') as stalls,
        count_if(event_type = 'retried') as retries,
        count_if(event_type = 'license_requested' and http_status = 403)
            as early_license_denials,
        count(*) as events
    from events
    group by run_id, client_id
)

select
    *,
    case
        when abandoned_at is not null then 'abandoned'
        when install_completed_at is not null then 'installed'
        when license_granted_at is not null then 'downloading'
        else 'waiting'
    end as status
from sessions
