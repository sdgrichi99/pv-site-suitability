{% macro weather_months() %}
  {% set months = var('months', none) %}
  {% if months is none %}
    {% set first_of_month = modules.datetime.date.today().replace(day=1) %}
    {% set previous = first_of_month - modules.datetime.timedelta(days=1) %}
    {{ return([previous.strftime('%Y-%m')]) }}
  {% endif %}
  {% if months is string %}
    {{ return([months]) }}
  {% endif %}
  {{ return(months) }}
{% endmacro %}

{# Elenco dei mesi come lista SQL: ('2026-09', '2026-10') #}
{% macro weather_months_sql() -%}
  ({%- for month in weather_months() -%}'{{ month }}'{{ ", " if not loop.last }}{%- endfor -%})
{%- endmacro %}
