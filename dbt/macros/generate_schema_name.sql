{#
    By default dbt prefixes custom schemas with the target schema
    ("analytics_staging"). Use the custom schema name as it is instead,
    so models land in "staging" and "marts".
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
