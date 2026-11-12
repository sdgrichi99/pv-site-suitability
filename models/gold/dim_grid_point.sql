{{ config(direct_create=true, tags=['monthly']) }}

with elevation as (
    select
        grid_id,
        max(elevation) as elevation_m
    from {{ ref('weather_hourly_brz') }}
    group by grid_id
)

select
    g.grid_id,
    g.latitude,
    g.longitude,
    e.elevation_m,
    g.land_fraction,
    g.cod_reg,
    g.den_reg,
    g.cod_prov,
    g.den_prov,
    g.sigla_prov,
    current_timestamp as _loaded_at
from {{ ref('grid_points') }} as g
left join elevation as e
    on g.grid_id = e.grid_id
