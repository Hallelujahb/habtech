# Pipeline 2, phase 2 -- AI-assisted matching for the national ID-mismatch
# cases. Standalone, does not touch dbt/Spark/Docker/Debezium. Reads the
# same two files national_link_compare.py already reads, does not modify
# anything in data_v2 except writing its own new output file.
#
# scope, deliberately: only the 633 facilities that HAVE a dhis2_id but it
# didn't match any uid in the dhis2 sheet -- typos, merged/retired DHIS2
# records, edits on one side not the other. The ~30,900 facilities with NO
# dhis2_id at all are a different, bigger problem (never tagged in DHIS2
# in the first place) and are intentionally left out of this script.

import os
import time
import pandas as pd
import linktransformer as lt

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    start = time.time()
    mfr = pd.read_csv(os.path.join(DATA_DIR, "mfr_facilities_202607291153.csv"), dtype=str)
    dhis2 = pd.read_excel(
        os.path.join(DATA_DIR, "dhis2_echis_mfr_facilities.xlsx"),
        sheet_name="dhis2", dtype=str,
    )

    dhis2_uids = set(dhis2["uid"].dropna())
    id_mismatch = mfr[mfr["dhis2_id"].notna() & ~mfr["dhis2_id"].isin(dhis2_uids)].copy()
    print(f"{len(id_mismatch)} facilities have a dhis2_id that didn't match -- these are the candidates")

    if len(id_mismatch) == 0:
        print("nothing to match, exiting")
        return

    print("loading embedding model and matching against the national dhis2 sheet "
          f"({len(dhis2)} candidates) -- this can take a few minutes, not seconds, "
          "given the pool size")

    matched = lt.merge_knn(
        id_mismatch[["id", "name", "region"]],
        dhis2[["uid", "name"]],
        model=MODEL,
        on="name",
        k=1,
        suffixes=("_mfr", "_dhis2"),
    )

    matched = matched.rename(columns={
        "id": "mfr_id",
        "name_mfr": "mfr_name",
        "name_dhis2": "best_candidate_name",
        "score": "similarity_score",
    })
    matched = matched[matched["similarity_score"] >= 0.75].copy()
    matched["needs_human_review"] = matched["similarity_score"] < 0.85

    out_path = os.path.join(DATA_DIR, "national_id_mismatch_matches.csv")
    matched.to_csv(out_path, index=False)
    print(f"\nwrote {len(matched)} candidate matches to {out_path}")
    print(f"finished in {time.time()-start:.1f}s")


if __name__ == "__main__":
    main()
