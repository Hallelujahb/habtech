# dbt Python model (runs via the dbt-postgres-python "fal" target, see
# ../../DBT_PYTHON_MODELS_NOTE.md for why Postgres needs that instead of
# dbt's native Python-model support). This is the piece that's genuinely
# awkward in plain SQL: loading an embedding model and scoring name
# similarity, versus a `select` dbt can already do fine.
#
# API note: dbt-postgres-python is a small, actively-maintained community
# package (successor to the archived dbt-fal), not one of dbt's officially
# supported adapters -- its exact `model(dbt, fal)` argument shape is
# worth confirming against https://pypi.org/project/dbt-postgres-python
# before the demo in case it's moved since this was written. The pattern
# below matches its documented usage as of when this was written.
#
# what it does: reads a scored table -- org unit, best candidate name,
# similarity score -- that's already been computed by LinkTransformer,
# and hands it to dbt to write into Postgres for a human to review and
# confirm before it's treated as a real link.
#
# IMPORTANT -- why this reads a CSV instead of calling LinkTransformer
# directly: it used to import match_unresolved_org_units() straight from
# linktransformer_examples/ and run it in-process. That doesn't work,
# permanently, regardless of which Python version or venv this runs in:
# dbt-postgres-python hard-pins pandas<2.0, and linktransformer requires
# pandas>=2.0 -- those two constraints can't both be satisfied in one
# Python process, on any interpreter. This isn't a version-pinning
# mistake to fix, it's two libraries with genuinely incompatible
# requirements. The fix is architectural: LinkTransformer runs separately,
# in the environment that already has it, and hands off through a file.
# Run linktransformer_examples/export_scored_matches.py BEFORE this dbt
# model (see NHDW_Demo_Commands_v3.txt step 10) -- it writes
# data_v2/facility_linkage_scored.csv, which is all this model reads.

import os

import pandas as pd

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
SCORED_CSV = os.path.join(HABTECH_HOME, "data_v2", "facility_linkage_scored.csv")


def model(dbt, fal):
    if not os.path.exists(SCORED_CSV):
        raise FileNotFoundError(
            f"{SCORED_CSV} not found -- run "
            "linktransformer_examples/export_scored_matches.py first "
            "(see NHDW_Demo_Commands_v3.txt step 10). This model reads "
            "its output rather than calling LinkTransformer in-process; "
            "see the note above for why."
        )
    return pd.read_csv(SCORED_CSV)
