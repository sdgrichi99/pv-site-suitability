{{ config(direct_create=true) }}

select
    c.customer_id,
    c.first_name || ' ' || c.last_name as full_name,
    c.email,
    count(o.order_id) as total_orders,
    coalesce(sum(o.amount), 0) as total_spent,
    max(o.order_date) as last_order_date
from {{ ref('customers_slv') }} c
left join {{ ref('orders_slv') }} o 
    on c.customer_id = o.customer_id
group by 1, 2, 3