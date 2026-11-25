{#
  17.5: a custom generic test -- a set of columns is unique together (one row
  per run and client, per run and POP). Same call as non_negative: no
  dbt_utils dependency for one check.
#}
{% test unique_combination(model, combination_of_columns) %}

select
    {{ combination_of_columns | join(', ') }},
    count(*) as n
from {{ model }}
group by {{ combination_of_columns | join(', ') }}
having count(*) > 1

{% endtest %}
