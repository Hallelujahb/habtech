# Pipeline 2 -- national scale. Standalone, does not touch dbt/Spark.
# Same join concept as pipeline 1 (mfr.dhis2_id == the DHIS2 side's own id),
# just against the "dhis2" sheet's uid column instead of org_units.csv,
# since that sheet is national (37,177 rows) while org_units.csv is Fafan-only.
import os, time
import pandas as pd

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")

def main():
    start = time.time()
    mfr = pd.read_csv(os.path.join(DATA_DIR, "mfr_facilities_202607291153.csv"), dtype=str)
    dhis2 = pd.read_excel(
        os.path.join(DATA_DIR, "dhis2_echis_mfr_facilities.xlsx"),
        sheet_name="dhis2", dtype=str,
    )

    merged = mfr.merge(dhis2, left_on="dhis2_id", right_on="uid", how="left", suffixes=("_mfr", "_dhis2"))
    merged["matched"] = merged["uid"].notna()

    summary = merged.groupby("region").agg(
        total_facilities=("id", "count"),
        matched=("matched", "sum"),
    ).reset_index()
    summary["unmatched"] = summary["total_facilities"] - summary["matched"]
    summary["match_rate_pct"] = (summary["matched"] / summary["total_facilities"] * 100).round(1)
    summary = summary.sort_values("total_facilities", ascending=False)

    print(summary.to_string(index=False))
    tagged = mfr["dhis2_id"].notna().sum()
    print(f"\noverall: {merged['matched'].sum()}/{tagged} facilities matched nationally "
          f"({100*merged['matched'].sum()/tagged:.1f}%)")

    out_path = os.path.join(DATA_DIR, "national_linkage_summary.csv")
    summary.to_csv(out_path, index=False)
    print(f"wrote {out_path}")
    print(f"finished in {time.time()-start:.1f}s")

if __name__ == "__main__":
    main()
