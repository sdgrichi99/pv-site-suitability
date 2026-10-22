select 
    101 as order_id,
    1 as customer_id,
    '2024-01-15'::date as order_date,
    150.50 as amount,
    'completed' as status
union all
select 
    102 as order_id,
    2 as customer_id,
    '2024-01-16'::date as order_date,
    200.00 as amount,
    'completed' as status
union all
select 
    103 as order_id,
    1 as customer_id,
    '2024-01-17'::date as order_date,
    50.25 as amount,
    'cancelled' as status