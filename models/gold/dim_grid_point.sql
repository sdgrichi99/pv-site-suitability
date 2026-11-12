{{ config(direct_create=true, tags=['monthly']) }}

with elevation as (
    select
        grid_id,
        max(elevation) as elevation_m
    from {{ ref('weather_hourly_brz') }}
    group by grid_id
)

select
    grid_points.grid_id,
    grid_points.latitude,
    grid_points.longitude,
    elv.elevation_m,
    grid_points.land_fraction,
    grid_points.cod_reg,
    grid_points.den_reg,
    grid_points.cod_prov,
    grid_points.den_prov,
    grid_points.sigla_prov,
    current_timestamp as _loaded_at
from {{ ref('grid_points') }} as grid_points
left join elevation as elv
    on grid_points.grid_id = elv.grid_id
