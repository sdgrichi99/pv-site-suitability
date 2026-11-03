{# Override di duckdb__drop_relation: drop senza "cascade". L'adapter non riconosce 'lakehouse' 
come DuckLake (e' agganciato dal plugin, non dal profilo) e userebbe "cascade", 
presumibilmente non supportato da DuckLake (da verificare). #}
{% macro duckdb__drop_relation(relation) -%}
  {% call statement('drop_relation') -%}
    drop {{ relation.type }} if exists {{ relation }}
  {%- endcall %}
{% endmacro %}
