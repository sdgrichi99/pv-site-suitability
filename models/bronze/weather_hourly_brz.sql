{#
  Bronze del meteo orario: una riga per punto della griglia e ora (UTC), cosi' come arriva dall'API.
  Legge i file in landing/weather_hourly/month=YYYY-MM/ e li appiattisce.

  Incrementale per mese: a ogni esecuzione sostituisce solo i mesi indicati da load_months()
  (di norma il mese precedente). Alla prima esecuzione o con --full-refresh rilegge tutto il landing.
#}
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='month_key',
    tags=['monthly', 'weather_hourly']
) }}

select
    grid_id,
    "month" as month_key,
    latitude,
    longitude,
    elevation,
    unnest(hourly.time) as observation_time,
    unnest(hourly.temperature_2m) as temperature_2m,
    unnest(hourly.relative_humidity_2m) as relative_humidity_2m,
    unnest(hourly.precipitation) as precipitation,
    unnest(hourly.wind_speed_10m) as wind_speed_10m,
    unnest(hourly.cloud_cover) as cloud_cover,
    unnest(hourly.shortwave_radiation) as shortwave_radiation,
    unnest(hourly.direct_radiation) as direct_radiation,
    unnest(hourly.diffuse_radiation) as diffuse_radiation,
    unnest(hourly.direct_normal_irradiance) as direct_normal_irradiance,
    unnest(hourly.sunshine_duration) as sunshine_duration,
    filename as _source_file,
    current_timestamp as _loaded_at
from read_json(
    {% if is_incremental() -%}
        [
            {%- for month in load_months() %}
                '{{ landing_path("weather_hourly") }}/month={{ month }}/*.json.gz'{{ "," if not loop.last }}
            {%- endfor %}
        ],
    {%- else -%}
        '{{ landing_path("weather_hourly") }}/*/*.json.gz',
    {%- endif %}
    format = 'array',
    filename = true,
    hive_partitioning = true,
    hive_types = { 'month': varchar },
    union_by_name = true
)
