{{ config(direct_create=true) }}

select
    customer_id,
    customer_name as first_name,
    last_name,
    lower(email) as email
from {{ ref('customers_brz') }}