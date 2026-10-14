# does the same job as dbt_clickhouse/models/fact_facility_ch.sql, in
# pandas instead of SQL -- NOT a dbt Python model, because dbt-clickhouse
# has no Python model support at all (see ../DBT_PYTHON_MODELS_NOTE.md).
# this runs standalone, on a schedule of its own (cron/Airflow), separate
# from `dbt run`.
#
# setup: pip install clickhouse-connect pandas

import os
import clickhouse_connect
import pandas as pd

CH_HOST = os.environ.get("CH_HOST", "localhost")
CH_USER = os.environ.get("CH_USER", "username")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "password")


def build_fact_facility_ch():
    client = clickhouse_connect.get_client(host=CH_HOST, username=CH_USER, password=CH_PASSWORD)

    df = client.query_df("SELECT * FROM default.mfr_facilities_ch")

    # same grouping fact_facility_ch.sql does: facility count and total
    # beds per region/zone/type, expressed as a pandas groupby instead of
    # a GROUP BY
    df["total_beds"] = (
        df["number_of_inpatient_beds"].fillna(0)
        + df["number_of_maternity_beds"].fillna(0)
        + df["number_of_emergency_beds"].fillna(0)
    )

    rollup = (
        df.groupby(["region", "zone", "type"], as_index=False)
        .agg(
            facility_count=("id", "count"),
            total_beds=("total_beds", "sum"),
            total_catchment_population=("catchment_population", "sum"),
        )
        .sort_values("facility_count", ascending=False)
    )
    rollup["avg_beds_per_facility"] = (rollup["total_beds"] / rollup["facility_count"]).round(1)
    rollup = rollup.rename(columns={"type": "facility_type"})

    client.command("""
        CREATE TABLE IF NOT EXISTS default.fact_facility_ch_py (
            region String, zone String, facility_type String,
            facility_count UInt32, total_beds UInt32,
            total_catchment_population UInt32, avg_beds_per_facility Float32
        ) ENGINE = MergeTree ORDER BY (region, zone, facility_type)
    """)
    client.command("TRUNCATE TABLE default.fact_facility_ch_py")
    client.insert_df("default.fact_facility_ch_py", rollup)

    print(f"wrote {len(rollup)} rollup rows to default.fact_facility_ch_py")
    return rollup


if __name__ == "__main__":
    result = build_fact_facility_ch()
    print(result.head(10).to_string(index=False))
