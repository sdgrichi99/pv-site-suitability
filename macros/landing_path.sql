{#
  Percorso S3 del landing di una sorgente, per il target corrente.
  Esempio: {{ landing_path('weather_forecast') }} -> s3://<bucket>/landing/weather_forecast
  Usa TIGRIS_BUCKET_DEV o TIGRIS_BUCKET_PRD, come ducklake_plugin e lo script di estrazione
  (orchestrate/extract/weather.py): i due devono scrivere e leggere lo stesso percorso.
#}
{% macro landing_path(source) -%}
  {{- env_var('TIGRIS_BUCKET_' ~ (target.name | upper)).rstrip('/') ~ '/landing/' ~ source -}}
{%- endmacro %}
