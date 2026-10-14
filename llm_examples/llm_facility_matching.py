# llm assisted facility matching, a standalone step that picks up exactly
# where the deterministic join (spark_link_compare.py / fact_linkage_audit)
# leaves off.
#
# the deterministic join matches org_units to the MFR on a shared id,
# dhis2_id, and resolves about 69% of the 492 org units in this catchment.
# the remaining ~150 have no shared id at all, only a name and a region,
# because they come from a separately, manually maintained DHIS2 regional
# bureau list (data_v2/dhis2_manual_registry_fafan.csv) rather than the
# same system that assigned the MFR's dhis2_id field.
#
# this script takes those unresolved org units (facility_linkage_unresolved.csv)
# and, for each one, asks an llm whether a given manual-registry name most
# likely refers to the same real facility, given both names and their region.
#
# setup:
#   pip install google-genai
#   export GEMINI_API_KEY=your_key_here
#
# free-tier Gemini caps at 5 requests/minute for this model. this script
# fires 3 calls per unresolved unit (one per candidate), so 2 units in
# already used most of that minute's budget, exactly the 429 you hit.
# fixed two ways below: pace every call to stay under the limit instead
# of firing them back to back, and back off automatically if a 429 slips
# through anyway (reading the server's own suggested wait time out of the
# error instead of guessing one).

import os
import csv
import json
import time
import re
from difflib import SequenceMatcher
from google import genai
from google.genai import errors as genai_errors

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")
SECONDS_BETWEEN_CALLS = 13  # 5/minute free-tier limit -> 12s minimum, +1s margin

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def llm_match_facility(name_a: str, region_a: str, name_b: str, region_b: str) -> dict:
    """
    asks the model whether two facility records most likely describe the
    same real health facility. returns a small structured verdict rather
    than free text, so it can be used programmatically in a pipeline.
    """
    prompt = f"""You are helping resolve two health facility records that may refer to the same real facility, reported by two different systems using different naming conventions.

Record A (DHIS2 org unit hierarchy): name="{name_a}", region="{region_a}"
Record B (manually maintained regional bureau list): name="{name_b}", region="{region_b}"

Decide if these most likely refer to the same real facility. Consider that
names may be abbreviated, reordered, or spelled slightly differently
across systems, but the underlying place should still be recognizable.

Respond with only a JSON object, no other text, in this exact shape:
{{"same_facility": true or false, "confidence": a number from 0 to 1, "reason": a short plain sentence}}"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
            )
            break
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) != 429 or attempt == 2:
                raise
            # pull the server's own suggested wait out of the error text
            # instead of guessing -- it already told us exactly how long
            match = re.search(r"retry in ([\d.]+)s", str(e), re.IGNORECASE)
            wait = float(match.group(1)) + 2 if match else 60
            print(f"  rate limited, waiting {wait:.0f}s before retrying...")
            time.sleep(wait)

    # gemini sometimes wraps json in a code fence even when asked not to,
    # strip that off before parsing so this does not break on a good answer
    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def top_candidates(target_name, pool, n=3):
    """cheap pre-filter before spending an llm call: rank the manual-registry
    pool by plain string similarity to the org unit name, keep the top n.
    the llm still makes the actual same/not-same call, this just avoids
    running it against all ~460 rows for every unresolved org unit."""
    scored = [
        (SequenceMatcher(None, target_name.lower(), row["name"].lower()).ratio(), row)
        for row in pool
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:n]]


if __name__ == "__main__":
    unresolved = load_rows(os.path.join(DATA_DIR, "facility_linkage_unresolved.csv"))
    manual_registry = load_rows(os.path.join(DATA_DIR, "dhis2_manual_registry_fafan.csv"))

    # demo run: first 2 unresolved org units (6 calls total) comfortably
    # fits one minute of the free tier's 5-request limit even with the
    # pacing below. bump this back up once on a paid tier / using Ollama
    # instead (see llm_facility_matching_local.py, no rate limit at all).
    first_call = True
    for org_unit in unresolved[:2]:
        candidates = top_candidates(org_unit["name"], manual_registry)
        print(f"\nUnresolved org unit: {org_unit['name']!r} ({org_unit.get('l3name', '')})")
        for cand in candidates:
            if not first_call:
                time.sleep(SECONDS_BETWEEN_CALLS)
            first_call = False
            result = llm_match_facility(
                org_unit["name"], org_unit.get("l3name", ""),
                cand["name"], cand.get("zonal", ""),
            )
            print(f"  vs {cand['name']!r} -> {result}")
