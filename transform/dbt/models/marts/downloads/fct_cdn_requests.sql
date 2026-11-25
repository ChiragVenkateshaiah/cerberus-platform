-- 17.5: the real CloudFront standard-log lines of a run, one row per request.
-- Allowlisted columns only, named one by one (never select *): the source
-- table has no client address, cookie, referer or user agent, and this model
-- never adds one.
--
-- run_id is the `run_id=` segment of "$path". Only part-* files are read (the
-- manifest is hidden by Athena, and filtered again here). Repeated collection
-- can duplicate lines, so the model keeps one row per x-edge-request-id.
-- The POP is the first 3 characters of x-edge-location (17.5 plan rule).
-- All values are strings in the
-- table, so a bad value becomes null (try_cast) and a test flags it.
-- timestamp(ms) is an epoch-ms number or an ISO-8601 string (unverified which
-- one the logs hold; both are handled).
with raw as (
    select
        "$path" as source_path,
        x_edge_request_id,
        timestamp_ms,
        x_edge_location,
        x_edge_result_type,
        x_edge_response_result_type,
        sc_status,
        sc_bytes,
        cs_method,
        cs_uri_stem,
        time_taken,
        time_to_first_byte,
        cs_protocol
    from {{ source('cerberus_downloads', 'bronze_downloads_cdn') }}
    where "$path" like '%/part-%'
),

typed as (
    select  -- noqa: ST06
        regexp_extract(source_path, '/run_id=([^/]+)/', 1) as run_id,
        x_edge_request_id as request_id,
        cast(
            coalesce(
                from_unixtime(try_cast(timestamp_ms as double) / 1000),
                try(from_iso8601_timestamp(timestamp_ms))
            ) as timestamp(6)
        ) as requested_at,
        x_edge_location as edge_location,
        substr(x_edge_location, 1, 3) as pop,
        x_edge_result_type as edge_result_type,
        x_edge_response_result_type as edge_response_result_type,
        try_cast(sc_status as integer) as status,
        try_cast(sc_bytes as bigint) as bytes,
        cs_method as http_method,
        cs_uri_stem as uri_stem,
        try_cast(time_taken as double) as time_taken_s,
        try_cast(time_to_first_byte as double) as server_ttfb_s,
        cs_protocol as protocol
    from raw
),

ranked as (
    select
        *,
        row_number() over (
            partition by request_id order by requested_at, run_id
        ) as rn
    from typed
)

select
    run_id,
    request_id,
    requested_at,
    edge_location,
    pop,
    edge_result_type,
    edge_response_result_type,
    status,
    bytes,
    http_method,
    uri_stem,
    time_taken_s,
    server_ttfb_s,
    protocol
from ranked
where rn = 1
