{% macro model_load_log_relation() %}
  {{ return(api.Relation.create(database='lakehouse_' ~ target.name, schema='audit', identifier='model_load_log')) }}
{% endmacro %}


{# on-run-start, primo passo: lo schema del registro #}
{% macro create_model_load_log_schema() %}
  create schema if not exists {{ model_load_log_relation().without_identifier() }}
{% endmacro %}


{# on-run-start, secondo passo: la tabella del registro #}
{% macro create_model_load_log() %}
  create table if not exists {{ model_load_log_relation() }} (
      model_name varchar,
      schema_name varchar,
      load_date date,
      month_key varchar,
      rows_inserted bigint,
      logged_at timestamp with time zone
  )
{% endmacro %}


{# post-hook dei modelli: {{ log_model_rows(this) }} #}
{% macro log_model_rows(relation, loaded_at_column='_loaded_at') %}
  {% if execute %}
    {% set columns = adapter.get_columns_in_relation(relation) | map(attribute='name') | map('lower') | list %}
    {% if loaded_at_column in columns %}
      {% if '_source_file' in columns %}
        {% set month_expression = "regexp_extract(_source_file, 'month=([0-9]{4}-[0-9]{2})', 1)" %}
      {% elif 'month_key' in columns %}
        {% set month_expression = "month_key" %}
      {% else %}
        {% set month_expression = "cast(null as varchar)" %}
      {% endif %}
      insert into {{ model_load_log_relation() }}
      select
          '{{ relation.identifier }}' as model_name,
          '{{ relation.schema }}' as schema_name,
          current_date as load_date,
          {{ month_expression }} as month_key,
          count(*) as rows_inserted,
          current_timestamp as logged_at
      from {{ relation }}
      where cast({{ loaded_at_column }} as date) = current_date
      group by {{ month_expression }}
    {% else %}
      {% do log("log_model_rows: " ~ relation ~ " non ha la colonna " ~ loaded_at_column ~ ", non entra nel registro", info=true) %}
    {% endif %}
  {% endif %}
{% endmacro %}
