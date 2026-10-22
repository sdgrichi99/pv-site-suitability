select
    order_id,
    customer_id,
    order_date,
    amount,
    upper(status) as status
from {{ ref('orders_brz') }}
where status != 'cancelled'