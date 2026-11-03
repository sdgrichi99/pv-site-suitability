{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='order_id'
) }}

select
    order_id,
    customer_id,
    order_date,
    amount,
    upper(status) as status,
    _loaded_at
from {{ ref('orders_brz') }}
where status != 'cancelled'
{% if is_incremental() %}
  and _loaded_at > (select coalesce(max(_loaded_at), timestamp '1900-01-01') from {{ this }})
{% endif %}
