-- 17.7: the release window of one exercise run (synthetic telemetry), from the
-- gold mart fct_release_window. {run_id} is the exercise run id, checked by
-- results_pull.py against its id pattern (lowercase letters, digits, hyphen; 1 to 40 characters) before it is put in. Bytes are in MB
-- as a decimal so that no value can hold a 12-digit run.
select
    run_id,
    region,
    cast(minute_at as varchar) as minute_at,
    minutes_from_release,
    license_requests,
    early_license_denials,
    licenses_granted,
    clients_with_chunk,
    cast(round(chunk_bytes / 1e6, 3) as decimal(18, 3)) as chunk_mb,
    stalls,
    installs
from cerberus_platform.fct_release_window
where run_id = '{run_id}'
order by region, minute_at
