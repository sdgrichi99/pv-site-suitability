
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='month_key',
    tags=['monthly', 'weather_hourly']
) }}

select
    grid_id,
    observation_date as weather_date,
    month_key,
    round(min(temperature_c), 1) as temp_min_c,
    round(max(temperature_c), 1) as temp_max_c,
    round(avg(temperature_c), 1) as temp_avg_c,
    round(avg(relative_humidity_pct), 0) as relative_humidity_avg_pct,
    round(sum(precipitation_mm), 1) as precipitation_mm,
    round(max(wind_speed_kmh), 1) as wind_max_kmh,
    round(avg(cloud_cover_pct), 0) as cloud_cover_avg_pct,
    round(sum(ghi_wm2) / 1000, 3) as ghi_kwh_m2,
    round(sum(direct_wm2) / 1000, 3) as direct_kwh_m2,
    round(sum(diffuse_wm2) / 1000, 3) as diffuse_kwh_m2,
    round(sum(dni_wm2) / 1000, 3) as dni_kwh_m2,
    round(sum(sunshine_s) / 3600, 2) as sunshine_hours,
    count(*) as hours_count,
    current_timestamp as _loaded_at
from {{ ref('weather_hourly_slv') }}
{% if is_incremental() %}
where month_key in {{ weather_months_sql() }}
{% endif %}
group by grid_id, observation_date, month_key
