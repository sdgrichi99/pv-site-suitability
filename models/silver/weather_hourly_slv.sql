{#
  Silver del meteo orario: una riga per punto della griglia e ora (UTC), con tipi e nomi puliti.
  Scarta le ore senza dati (l'archivio ERA5 ha un ritardo di circa 5 giorni sui dati piu' recenti).

  Le grandezze di irraggiamento sono la media sull'ora precedente, in W/m2; precipitazione e
  durata del soleggiamento sono la somma sull'ora precedente.

  Incrementale per mese, come il bronze.
#}
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='month_key',
    tags=['monthly', 'weather_hourly']
) }}

select
    grid_id,
    cast(observation_time as timestamp) as observation_ts,
    cast(cast(observation_time as timestamp) as date) as observation_date,
    month_key,
    cast(temperature_2m as double) as temperature_c,
    cast(relative_humidity_2m as double) as relative_humidity_pct,
    cast(precipitation as double) as precipitation_mm,
    cast(wind_speed_10m as double) as wind_speed_kmh,
    cast(cloud_cover as double) as cloud_cover_pct,
    cast(shortwave_radiation as double) as ghi_wm2,
    cast(direct_radiation as double) as direct_wm2,
    cast(diffuse_radiation as double) as diffuse_wm2,
    cast(direct_normal_irradiance as double) as dni_wm2,
    cast(sunshine_duration as double) as sunshine_s,
    current_timestamp as _loaded_at
from {{ ref('weather_hourly_brz') }}
where
    observation_time is not null
    and temperature_2m is not null
    {% if is_incremental() %}
        and month_key in {{ weather_months_sql() }}
    {% endif %}
