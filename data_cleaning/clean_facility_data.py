"""
Data cleaning step for the NHDW facility datasets.

Runs BEFORE the deterministic linking join (dhis2_id == org_units.id),
because cleaning has to happen before linking, not after -- a join can
only be as good as the keys and names going into it.

Every transformation below was chosen because it showed up as a real,
measured problem in the actual uploaded files (see the printed counts),
not a generic checklist. Run this file directly to see the before/after
numbers for whichever scale you point DATA_DIR at.
"""

import os
import re
import pandas as pd

DATA_DIR = os.environ.get("HABTECH_DATA_DIR", os.path.expanduser("~/habtech/data_v2"))

# Ethiopian -> Gregorian calendar, month-name lookup.
# Ethiopian New Year (Meskerem 1) falls ~Sept 11 Gregorian, so the 13-month
# Ethiopian year spans two Gregorian years. This uses the standard
# approximation: months 1-4 (Meskerem-Tahsas, ~Sept-Jan) => ET year + 7,
# months 5-13 (Tir-Pagume, ~Jan-Sept) => ET year + 8. Good to the year,
# not the exact day -- fine for a "year_opened" field, not a legal record.
ETHIOPIAN_MONTHS = {
    "መስከረም": 1, "ጥቅምት": 2, "ኅዳር": 3, "ህዳር": 3, "ታኅሳስ": 4, "ታህሳስ": 4,
    "ጥር": 5, "የካቲት": 6, "መጋቢት": 7, "ሚያዝያ": 8, "ግንቦት": 9, "ሰኔ": 10,
    "ሐምሌ": 11, "ሀምሌ": 11, "ነሐሴ": 12, "ነሀሴ": 12, "ጳጉሜ": 13, "ጳጉሜን": 13,
}

ET_BBOX = dict(lat_min=3.0, lat_max=15.0, lon_min=33.0, lon_max=48.0)


def ethiopian_to_gregorian_year(date_str):
    if not isinstance(date_str, str) or "," not in date_str:
        return None
    month_word = date_str.split()[0].strip()
    month_num = ETHIOPIAN_MONTHS.get(month_word)
    if month_num is None:
        return None
    try:
        et_year = int(date_str.split(",")[-1].strip())
    except ValueError:
        return None
    return et_year + 7 if month_num <= 4 else et_year + 8


def clean_facility_registry(path_in, path_out, tag):
    df = pd.read_csv(path_in, low_memory=False)
    n = len(df)
    log = [f"\n=== cleaning {os.path.basename(path_in)} ({tag}, {n:,} rows) ==="]

    # 1. trim whitespace on every text column
    text_cols = df.select_dtypes(include="object").columns
    before = sum((df[c].astype(str) != df[c].astype(str).str.strip()).sum() for c in text_cols)
    for c in text_cols:
        df[c] = df[c].astype(str).where(df[c].notna(), df[c]).apply(
            lambda v: v.strip() if isinstance(v, str) else v
        )
    log.append(f"  trimmed whitespace: {before:,} cells affected")

    # 2. fix names that start with a lowercase letter (data-entry casing errors)
    #    only the first character is touched -- full title-casing would break
    #    real acronyms already in these names (PHCU, IDP, OPD, etc.)
    def fix_leading_case(name):
        if isinstance(name, str) and name and name[0].islower():
            return name[0].upper() + name[1:]
        return name
    lower_before = df["name"].astype(str).str[0].str.islower().sum()
    df["name"] = df["name"].apply(fix_leading_case)
    log.append(f"  fixed lowercase-leading facility names: {lower_before:,}")

    # 3. standardize zone naming so it can be matched by NAME against
    #    org_units, not just by id. org_units uses "Fafan Zone", mfr uses
    #    "Fafan" -- neither is wrong, they just don't line up.
    df["zone_normalized"] = df["zone"].astype(str).str.replace(
        r"\s+Zone$", "", regex=True
    ).str.strip().str.lower()
    log.append("  added zone_normalized column (strips ' Zone' suffix, lowercases)")

    # 4. validate coordinates against Ethiopia's real bounding box; anything
    #    outside it is a bad geocode, not a fact -- null it out rather than
    #    plot a facility in the Indian Ocean
    bad_geo = df["latitude"].notna() & (
        (df["latitude"] < ET_BBOX["lat_min"]) | (df["latitude"] > ET_BBOX["lat_max"]) |
        (df["longitude"] < ET_BBOX["lon_min"]) | (df["longitude"] > ET_BBOX["lon_max"])
    )
    df.loc[bad_geo, ["latitude", "longitude"]] = None
    log.append(f"  nulled out-of-Ethiopia coordinates: {int(bad_geo.sum()):,} rows")

    # 5. convert year_opened from Ethiopian calendar text to a Gregorian year
    df["year_opened_gregorian"] = df["year_opened"].apply(ethiopian_to_gregorian_year)
    converted = df["year_opened_gregorian"].notna().sum()
    log.append(f"  converted year_opened (Ethiopian calendar) to Gregorian year: {converted:,} rows")

    # 6. distinguish "zero beds reported" from "not reported at all" before
    #    any downstream model coalesces blanks to 0 -- otherwise a missing
    #    value and a real zero look identical
    df["beds_reported"] = df["number_of_inpatient_beds"].notna()
    not_reported = (~df["beds_reported"]).sum()
    log.append(f"  flagged beds_reported (vs silently coalesced to 0): {not_reported:,} rows not reported")

    # 7. write whole-number columns as actual integers, not floats. pandas
    #    silently upgrades any numeric column containing a blank to
    #    float64, so without this every one of these gets written to CSV
    #    as "9.0" instead of "9" -- which then breaks a plain ::int cast
    #    in Postgres, since Postgres's text->int cast rejects decimal
    #    points outright (real bug, hit on the first real run of this
    #    pipeline, fixed here at the source instead of papering over it
    #    downstream). pandas' nullable Int64 dtype keeps blanks blank
    #    instead of turning them into "9.0" or a literal "nan" string.
    whole_number_cols = [
        "number_of_inpatient_beds", "number_of_maternity_beds", "number_of_emergency_beds",
        "number_of_opd_rooms", "number_of_ipd_rooms", "number_of_laboratory_rooms",
        "number_of_imaging_rooms", "number_of_mch_rooms", "number_of_icu_rooms",
        "catchment_population", "year_opened_gregorian",
    ]
    for col in whole_number_cols:
        if col in df.columns:
            df[col] = df[col].round().astype("Int64")
    log.append(f"  wrote {len(whole_number_cols)} numeric columns as clean integers, not '9.0'-style floats")

    # 8. duplicate id check
    dupes = df["id"].duplicated().sum()
    log.append(f"  duplicate ids found: {dupes}")

    df.to_csv(path_out, index=False)
    log.append(f"  wrote {path_out} ({len(df):,} rows)")
    print("\n".join(log))
    return log


def clean_org_units(path_in, path_out):
    df = pd.read_csv(path_in)
    log = [f"\n=== cleaning {os.path.basename(path_in)} ({len(df):,} rows) ==="]

    text_cols = ["name", "shortname", "l1name", "l2name", "l3name", "l4name", "l5name", "l6name"]
    before = 0
    for c in text_cols:
        if c in df.columns:
            mask = df[c].astype(str) != df[c].astype(str).str.strip()
            before += mask.sum()
            df[c] = df[c].astype(str).apply(lambda v: v.strip() if isinstance(v, str) else v)
    log.append(f"  trimmed whitespace: {int(before):,} cells affected")

    df["zone_normalized"] = df["l3name"].astype(str).str.replace(
        r"\s+Zone$", "", regex=True
    ).str.strip().str.lower()
    log.append("  added zone_normalized column, same convention as the facility registry")

    df.to_csv(path_out, index=False)
    log.append(f"  wrote {path_out} ({len(df):,} rows)")
    print("\n".join(log))
    return log


if __name__ == "__main__":
    all_log = []
    all_log += clean_facility_registry(
        f"{DATA_DIR}/master_facility_registry.csv",
        f"{DATA_DIR}/master_facility_registry_clean.csv", "Fafan Zone, Somali Region")
    all_log += clean_org_units(
        f"{DATA_DIR}/org_units.csv",
        f"{DATA_DIR}/org_units_clean.csv")

    with open(f"{DATA_DIR}/../DATA_CLEANING_LOG.md", "w") as f:
        f.write("# Data cleaning log\n\nGenerated by clean_facility_data.py\n\n```\n")
        f.write("\n".join(all_log))
        f.write("\n```\n")
