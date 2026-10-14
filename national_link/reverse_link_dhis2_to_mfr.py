# Pipeline 2, phase 3 -- reverse-direction AI matching.
# Standalone. Does not touch Postgres/Kafka/Debezium/dbt/Spark at all --
# reads two files, embeds two name lists, writes one output csv.
#
# direction: for each of the 8,796 dhis2-sheet records that no MFR row
# points to, find its closest name match among the 30,901 MFR facilities
# that have no dhis2_id at all. Same open question as the forward
# direction (the 633 case) -- these are two different-looking gaps that
# may be the same real facilities, just never cross-tagged.

import os
import time
import pandas as pd
import openpyxl
import linktransformer as lt

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_dhis2_sheet():
    wb = openpyxl.load_workbook(
        os.path.join(DATA_DIR, "dhis2_echis_mfr_facilities.xlsx"),
        read_only=True, data_only=True,
    )
    ws = wb["dhis2"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    return pd.DataFrame(rows, columns=header)


def main():
    start = time.time()

    mfr = pd.read_csv(os.path.join(DATA_DIR, "mfr_facilities_202607291153.csv"), dtype=str)
    dhis2 = load_dhis2_sheet()

    # forward-referenced uids (same logic as the earlier forward check)
    referenced_uids = set(mfr.loc[mfr["dhis2_id"].notna(), "dhis2_id"]) & set(dhis2["uid"].dropna())

    unreferenced_dhis2 = dhis2[~dhis2["uid"].isin(referenced_uids)].dropna(subset=["name"]).copy()
    no_id_mfr = mfr[mfr["dhis2_id"].isna() | (mfr["dhis2_id"] == "")].dropna(subset=["name"]).copy()

    print(f"{len(unreferenced_dhis2)} unreferenced dhis2 records")
    print(f"{len(no_id_mfr)} MFR facilities with no dhis2_id at all")
    print("loading embedding model and matching -- this pool is bigger than "
          "anything run so far, expect several minutes, not seconds")

    matched = lt.merge_knn(
        unreferenced_dhis2[["uid", "name", "regional"]],
        no_id_mfr[["id", "name", "region"]],
        model=MODEL,
        on="name",
        k=1,
        suffixes=("_dhis2", "_mfr"),
    )

    matched = matched.rename(columns={
        "uid": "dhis2_uid",
        "name_dhis2": "dhis2_name",
        "regional": "dhis2_regional_bureau",
        "id": "mfr_id",
        "name_mfr": "mfr_candidate_name",
        "region": "mfr_region",
        "score": "similarity_score",
    })
    matched = matched[matched["similarity_score"] >= 0.75].copy()
    matched["needs_human_review"] = matched["similarity_score"] < 0.85

    out_path = os.path.join(DATA_DIR, "reverse_link_dhis2_to_mfr.csv")
    matched.to_csv(out_path, index=False)
    print(f"\nwrote {len(matched)} candidate matches to {out_path}")
    print(f"finished in {time.time()-start:.1f}s")


if __name__ == "__main__":
    main()
