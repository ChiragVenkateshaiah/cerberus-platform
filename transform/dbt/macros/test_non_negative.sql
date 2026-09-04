{#
  6.3: a custom generic test -- amounts should never be negative. No
  dbt_utils dependency added for one check (dbt_utils.accepted_range would
  do this too); this is the same "simplest correct option, no new moving
  part for one thing" call this project has made elsewhere (1.7's
  full-rebuild transform, no incremental logic; the freshness probe's
  plain boto3 handler, no dependency layer).
#}
{% test non_negative(model, column_name) %}

select *
from {{ model }}
where {{ column_name }} < 0

{% endtest %}
