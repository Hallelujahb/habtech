# same facility-matching task as llm_facility_matching.py, same prompt,
# same pre-filter -- the only thing that changes is where the model runs.
#
# Ollama (https://github.com/ollama/ollama, MIT licensed) runs open-weight
# models locally and exposes a plain local HTTP API, no account, no API
# key, nothing leaves this machine. good option if the answer to
# DATA_GOVERNANCE_NOTE.md's question needs to be "nothing left the
# building at all," or if there's no Gemini key handy for a rehearsal.
#
# setup (one time):
#   curl -fsSL https://ollama.com/install.sh | sh
#   ollama pull llama3.2
#   ollama serve &   (skip this if `ollama pull` already started the service)
#
# tradeoff worth saying out loud in the demo: a small local model like
# llama3.2:3b is noticeably less reliable at this specific judgment call
# than Gemini's hosted model, expect to see it flip on borderline cases
# that Gemini gets right. that's a real, honest limitation of running
# something small enough to fit on a laptop, not a bug in this script.

import os
import csv
import json
import requests
from difflib import SequenceMatcher

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")


def llm_match_facility(name_a: str, region_a: str, name_b: str, region_b: str) -> dict:
    prompt = f"""You are helping resolve two health facility records that may refer to the same real facility, reported by two different systems using different naming conventions.

Record A (DHIS2 org unit hierarchy): name="{name_a}", region="{region_a}"
Record B (manually maintained regional bureau list): name="{name_b}", region="{region_b}"

Decide if these most likely refer to the same real facility. Consider that
names may be abbreviated, reordered, or spelled slightly differently
across systems, but the underlying place should still be recognizable.

Respond with only a JSON object, no other text, in this exact shape:
{{"same_facility": true or false, "confidence": a number from 0 to 1, "reason": a short plain sentence}}"""

    resp = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    })
    resp.raise_for_status()
    text = resp.json()["response"].strip()
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
    scored = [
        (SequenceMatcher(None, target_name.lower(), row["name"].lower()).ratio(), row)
        for row in pool
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:n]]


if __name__ == "__main__":
    unresolved = load_rows(os.path.join(DATA_DIR, "facility_linkage_unresolved.csv"))
    manual_registry = load_rows(os.path.join(DATA_DIR, "dhis2_manual_registry_fafan.csv"))

    for org_unit in unresolved[:5]:
        candidates = top_candidates(org_unit["name"], manual_registry)
        print(f"\nUnresolved org unit: {org_unit['name']!r} ({org_unit.get('l3name', '')})")
        for cand in candidates:
            result = llm_match_facility(
                org_unit["name"], org_unit.get("l3name", ""),
                cand["name"], cand.get("zonal", ""),
            )
            print(f"  vs {cand['name']!r} -> {result}")
