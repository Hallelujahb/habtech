# Writes match_unresolved_org_units()'s output to a CSV that
# dbt_postgres_python/models/fact_linkage_scored.py reads instead of
# importing linktransformer directly.
#
# why this exists: dbt-postgres-python (the "fal" adapter that makes the
# dbt Python model possible at all) hard-pins pandas<2.0. linktransformer
# requires pandas>=2.0 (pinned to 3.0.0 as of the version on PyPI when
# this was checked). Those two constraints are mutually exclusive in a
# single Python process, on any Python version -- not a version-pinning
# oversight, a real conflict between two libraries' declared
# requirements. See DBT_PYTHON_MODELS_NOTE.md for the full explanation.
#
# the fix is architectural, not a pip flag: run linktransformer here, in
# the environment that already has it (the one habtech_setup.sh builds,
# with modern pandas), and hand the result to the dbt Python model as a
# plain CSV. the dbt Python model then only needs pandas to read a CSV --
# something pandas<2.0 does just fine -- and never imports linktransformer
# at all, so the conflict never occurs in that process to begin with.
#
# run this BEFORE `dbt run` in dbt_postgres_python/ (see
# NHDW_Demo_Commands_v3.txt step 10). same venv as
# linktransformer_facility_matching.py -- no new install needed.

import os

from linktransformer_facility_matching import match_unresolved_org_units

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
OUT_PATH = os.path.join(HABTECH_HOME, "data_v2", "facility_linkage_scored.csv")


def main():
    scored = match_unresolved_org_units(top_n=1)

    name_col = "name_org_unit" if "name_org_unit" in scored.columns else "name_x"
    match_col = "name_manual_registry" if "name_manual_registry" in scored.columns else "name_y"

    out = scored[["id", name_col, match_col, "score"]].rename(columns={
        "id": "org_unit_id",
        name_col: "org_unit_name",
        match_col: "best_candidate_name",
        "score": "similarity_score",
    })
    out["needs_human_review"] = out["similarity_score"] < 0.85

    out.to_csv(OUT_PATH, index=False)
    print(f"wrote {len(out)} scored matches to {OUT_PATH}")
    print(f"  {out['needs_human_review'].sum()} flagged for human review (similarity < 0.85)")


if __name__ == "__main__":
    main()
