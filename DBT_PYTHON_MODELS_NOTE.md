# dbt with Python models instead of SQL — what's actually possible here

The honest version first, because "just do dbt in Python" runs into a real
platform limit, not a skill-issue one.

## The actual constraint

dbt-core's native Python model feature (`.py` files in a `models/`
folder, `def model(dbt, session): ... return df`) only runs on adapters
whose warehouse can execute Python remotely: **Snowflake (Snowpark),
Databricks (PySpark), and BigQuery (Dataproc/BigFrames)**. That's it, as
of dbt-core through the 1.11 line. Neither of this project's two
warehouses supports it:

- **dbt-clickhouse says so directly in its own changelog**: *"Does NOT add
  support for Python models (not implemented)"* — ClickHouse has no
  remote Python execution engine for dbt to hand a session to.
- **dbt-postgres has never added it either** — plain Postgres has no
  built-in Python runtime dbt could target the way Snowflake has
  Snowpark.

This isn't a config flag we forgot to set; it's a real gap in what those
two adapters expose. Anyone who says "just write a `.py` model" without
naming which of the three supported platforms they mean is either
thinking of Databricks/Snowflake, or hasn't hit this wall yet.

## What's actually built here instead, and why each is the honest fix

### Postgres: `dbt_postgres_python/` uses `dbt-postgres-python`

A real, maintained community adapter (`pip install dbt-postgres-python`,
successor to the archived `dbt-fal` project) that adds a second profile
target of type `fal` sitting in front of the normal `postgres` target. It
runs the Python model's code as a plain local Python process, and
`dbt.ref()` inside it fetches the referenced table as a pandas
DataFrame; the return value gets written back into Postgres as a new
table. This is a real workaround, not dbt's native Python-model feature,
but the code you write looks and behaves the same way.

**A real, confirmed constraint, and how it's worked around:**
`dbt-postgres-python` hard-pins `pandas<2.0` (confirmed against its own
PyPI metadata for every released version: 1.5.9, 1.6.16, 1.7.17 all pin
`pandas<2.0.0`). `linktransformer` requires `pandas>=2.0` (pinned to a
specific 2.x/3.x release). Those two constraints cannot both be
satisfied in a single Python process, on any Python version — this
isn't a version-pinning oversight to patch, it's two libraries with
genuinely incompatible requirements.

There's a second, separate wrinkle on top of that: `pandas<2.0` has
never had a prebuilt wheel published for Python 3.12 at all (checked
directly against PyPI's wheel listing) — only 3.10 and 3.11. So
`dbt-postgres-python` needs its own venv on an older Python
(`dbt_python_venv/`, built by `habtech_setup.sh`), separate from
`dbt_venv/` (which runs `dbt-postgres`/`dbt-clickhouse` fine on 3.12).

Because of the first constraint, `models/fact_linkage_scored.py` does
**not** import LinkTransformer directly. It used to, and that's exactly
what broke: pandas<2.0 and pandas>=2.0 in the same process. Instead, the
work is split across two processes handed off through a file:

1. `linktransformer_examples/export_scored_matches.py` runs in the main
   environment (the one `habtech_setup.sh` builds with modern pandas,
   which already has LinkTransformer), scores the unresolved org units,
   and writes `data_v2/facility_linkage_scored.csv`.
2. `models/fact_linkage_scored.py` runs in `dbt_python_venv/` (old
   pandas, no LinkTransformer installed or needed) and just reads that
   CSV with `pd.read_csv()` — something pandas<2.0 does natively, no
   conflicting import required.

Run them in that order — see `NHDW_Demo_Commands_v3.txt` step 10.

### ClickHouse: no dbt Python model — a plain Python script instead

Since there's no adapter that adds this for ClickHouse, honesty means not
pretending a `.py` file dropped into `dbt_clickhouse/models/` would do
anything. `dbt_clickhouse_python/build_fact_facility_ch.py` does the same
transformation as `dbt_clickhouse/models/fact_facility_ch.sql`, but
written as a standalone pandas script that reads from ClickHouse via
`clickhouse-connect`, transforms, and writes the result back — run
directly (`python3 build_fact_facility_ch.py`) or from cron/Airflow, not
through `dbt run`. It sits next to the SQL model rather than replacing
it, so both are there to compare directly, the same "two ways, compare
them" idea `spark_link_compare.py` already uses for the join.

## Setup

Handled automatically by `habtech_setup.sh`, which builds a **separate**
`dbt_python_venv/` on Python 3.10 or 3.11 (installing that interpreter
first if it's not already present) and installs `dbt-postgres-python`
there — deliberately not the same `dbt_venv/` used for
`dbt-postgres`/`dbt-clickhouse`, and deliberately without LinkTransformer
in it (see the constraint explained above). This step is best-effort and
non-fatal: if no 3.10/3.11 interpreter can be found or installed, setup
prints a note and moves on — steps 1-9 are unaffected either way.

To do it by hand instead:
```
python3.11 -m venv ~/habtech/dbt_python_venv
~/habtech/dbt_python_venv/bin/pip install --upgrade pip
~/habtech/dbt_python_venv/bin/pip install --only-binary=:all: dbt-postgres-python
```

## Running it

Two commands, two different environments, in this order:

```
cd ~/habtech/linktransformer_examples
python3 export_scored_matches.py

cd ~/habtech/dbt_postgres_python
~/habtech/dbt_python_venv/bin/dbt run --profiles-dir profiles
```

The first command is slow the first time (loading the LinkTransformer
embedding model), same "first run downloads/loads something big, that's
normal" note as `spark_link_compare.py` and
`linktransformer_facility_matching.py`. The second command just reads a
CSV, so it's fast every time.
