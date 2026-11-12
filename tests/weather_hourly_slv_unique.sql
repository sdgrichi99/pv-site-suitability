-- Una sola riga per punto della griglia e ora nel silver orario
select
    grid_id,
    observation_ts,
    count(*) as righe
from {{ ref('weather_hourly_slv') }}
group by grid_id, observation_ts
having count(*) > 1
