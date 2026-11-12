{# Percorso del file di esportazione di una tabella, per il target corrente #}
{% macro export_path(relation) -%}
  {{- env_var('TIGRIS_BUCKET_' ~ (target.name | upper)).rstrip('/') ~ '/export/' ~ relation.schema ~ '/' ~ relation.identifier ~ '.parquet' -}}
{%- endmacro %}


{# post-hook: scrive l'intera tabella nel file di esportazione #}
{% macro export_table(relation) %}
  copy (select * from {{ relation }})
  to '{{ export_path(relation) }}'
  (format parquet, compression zstd)
{% endmacro %}
