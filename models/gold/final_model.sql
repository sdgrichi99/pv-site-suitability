{{ config(direct_create=true) }}

SELECT
    range AS customer_id,
    'Customer_' || range AS customer_name,
    'user_' || range || '@example.com' AS email,
    CURRENT_TIMESTAMP AS created_at
FROM range(100000)