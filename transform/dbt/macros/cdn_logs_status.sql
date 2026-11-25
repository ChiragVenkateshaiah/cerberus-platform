{#- 17.5: complete / partial / unknown for a run's CDN logs (ADR 0030 Decision 13).
    `lines` is the distinct x-edge-request-id count of the run; the k6 count comes
    from the var k6_requests_by_run. A missing or non-positive count is unknown,
    which readers treat as partial. 99 is the ADR's threshold. -#}
{% macro cdn_logs_status(lines, run_id_column) %}
case
    {%- for run_id, k6 in var('k6_requests_by_run', {}).items() %}
    {%- if k6 is integer and k6 > 0 %}
    when {{ run_id_column }} = '{{ run_id }}'
        then case when {{ lines }} * 100 >= 99 * {{ k6 }} then 'complete' else 'partial' end
    {%- endif %}
    {%- endfor %}
    else 'unknown'
end
{% endmacro %}
