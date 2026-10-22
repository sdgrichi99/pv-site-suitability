select
    customer_id,
    trim(first_name) as first_name,
    last_name,
    lower(email) as email
from {{ ref('customers_brz') }}