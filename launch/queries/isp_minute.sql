-- 17.7: modelled Gbps per ISP and minute of one exercise run, from the gold mart
-- fct_isp_minute. Modelled, not measured (see the mart). {run_id} is the exercise
-- run id. Decimals are rounded so no value can hold a 12-digit run.
select
    run_id,
    isp,
    cast(minute_at as varchar) as minute_at,
    active_clients,
    stalled_clients,
    cast(round(modelled_gbps, 6) as decimal(18, 6)) as modelled_gbps,
    cast(round(stall_rate, 6) as decimal(9, 6)) as stall_rate
from cerberus_platform.fct_isp_minute
where run_id = '{run_id}'
order by isp, minute_at
