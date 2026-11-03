{{ config(direct_create=true) }}

{% set phase = var('orders_test_phase', 2) | int %}

select 101 as order_id, 1 as customer_id, '2024-01-15'::date as order_date,
       {{ '175.00' if phase >= 2 else '150.50' }} as amount, 'completed' as status,
       {{ "timestamp '2026-11-02 09:00:00'" if phase >= 2 else "timestamp '2026-11-02 08:00:00'" }} as _loaded_at
union all
select 102, 2, '2024-01-16'::date, 200.00, 'completed', timestamp '2026-11-02 08:00:00'
union all
select 103, 1, '2024-01-17'::date, 50.25, 'cancelled', timestamp '2026-11-02 08:00:00'
{% if phase >= 2 %}
union all
select 104, 2, '2024-01-18'::date, 90.00, 'completed', timestamp '2026-11-02 09:00:00'
{% endif %}
