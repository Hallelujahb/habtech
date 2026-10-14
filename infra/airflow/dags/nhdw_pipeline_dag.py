"""
NHDW pipeline, orchestrated. This replaces the manual "run this, then
this, then this" sequence from NHDW_Demo_Commands_v2.txt with real
scheduling, retries, and dependency tracking.

Mirrors the actual data flow: clean -> ingest -> transform (SQL) ->
transform (Spark, parallel) -> AI-linking -> load ClickHouse -> dbt
Python model. Kafka/Debezium is NOT in this DAG on purpose -- CDC is
continuous streaming, not a scheduled batch step, so it runs
independently as its own long-lived service, not a DAG task.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "nhdw",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,  # wire up alerting via the on_failure_callback below instead
}

with DAG(
    dag_id="nhdw_pipeline",
    default_args=default_args,
    description="Clean -> ingest -> transform -> link -> load, full NHDW pipeline",
    schedule="0 */6 * * *",   # every 6 hours; tune to real ingestion cadence
    start_date=datetime(2026, 1, 1),
    catchup=False,             # don't backfill every missed interval on first deploy
    max_active_runs=1,         # don't let two runs overlap and race on Postgres
    tags=["nhdw", "etl"],
) as dag:

    clean_data = BashOperator(
        task_id="clean_facility_data",
        bash_command="python3 {{ var.value.nhdw_home }}/data_cleaning/clean_facility_data.py",
    )

    ingest = BashOperator(
        task_id="meltano_ingest",
        bash_command=(
            "cd {{ var.value.nhdw_home }}/meltano_project && "
            "meltano run tap-csv target-postgres"
        ),
    )

    dbt_sql_transform = BashOperator(
        task_id="dbt_run_postgres",
        bash_command=(
            "cd {{ var.value.nhdw_home }}/dbt_postgres && "
            "{{ var.value.dbt_venv }}/bin/dbt run --profiles-dir profiles"
        ),
    )

    dbt_test = BashOperator(
        task_id="dbt_test_postgres",
        bash_command=(
            "cd {{ var.value.nhdw_home }}/dbt_postgres && "
            "{{ var.value.dbt_venv }}/bin/dbt test --profiles-dir profiles"
        ),
    )

    spark_compare = BashOperator(
        task_id="spark_link_compare",
        bash_command="cd {{ var.value.nhdw_home }}/spark && python3 spark_link_compare.py",
    )

    ai_linking = BashOperator(
        task_id="linktransformer_matching",
        bash_command=(
            "cd {{ var.value.nhdw_home }}/linktransformer_examples && "
            "python3 linktransformer_facility_matching.py"
        ),
    )

    load_clickhouse = BashOperator(
        task_id="load_clickhouse_raw",
        bash_command=(
            "docker exec -i clickhouse clickhouse-client --user username "
            "--password {{ var.value.clickhouse_password }} --query "
            "'INSERT INTO default.mfr_facilities_ch FORMAT CSVWithNames' < "
            "{{ var.value.nhdw_home }}/data_v2/master_facility_registry_clean.csv"
        ),
    )

    dbt_clickhouse_transform = BashOperator(
        task_id="dbt_run_clickhouse",
        bash_command=(
            "cd {{ var.value.nhdw_home }}/dbt_clickhouse && "
            "{{ var.value.dbt_venv }}/bin/dbt run --profiles-dir profiles"
        ),
    )

    # dependency graph -- this is the part a manual runbook can't give
    # you: real parallelism (spark_compare and ai_linking both wait on
    # ingest, but not on each other) and real failure isolation (if
    # ai_linking fails, load_clickhouse still doesn't run, but dbt_test
    # failing doesn't block spark_compare, since they're independent
    # branches).
    clean_data >> ingest
    ingest >> dbt_sql_transform >> dbt_test
    ingest >> spark_compare
    ingest >> ai_linking
    [spark_compare, ai_linking] >> load_clickhouse >> dbt_clickhouse_transform
