# same job as llm_examples/llm_facility_matching.py -- resolve the ~150
# org units that have no shared id with the MFR, only a name and a region --
# done with LinkTransformer instead of a general-purpose chat LLM.
#
# https://github.com/dell-research-harvard/linktransformer
# Arora & Dell, "LinkTransformer: A Unified Package for Record Linkage with
# Transformer Language Models" (arXiv:2309.00789)
#
# why this instead of Gemini/Ollama: those two ask a chat model to reason
# in free text about whether two strings name the same place, one pair at a
# time, and then a regex has to pull a json verdict back out of whatever it
# said. that works, but it's the wrong tool -- record linkage is a
# well-studied problem with purpose-built models for it. LinkTransformer
# wraps a sentence-transformers embedding model that was specifically
# trained (or fine-tuned) for "do these two strings refer to the same
# entity", and gives back a numeric similarity score for every candidate at
# once via nearest-neighbor search (faiss under the hood), not a
# one-verdict-per-API-call loop. concretely that means:
#   - no API key, no per-call network round trip, no rate limit -- the
#     model runs locally, same as the Ollama option, but faster and without
#     needing a full LLM runtime installed
#   - a numeric score you can threshold and tune, not a free-text "reason"
#     string you have to trust
#   - it was built for exactly this (merge/dedup/cluster dataframes), so the
#     top-3-candidates-per-row shape below is one function call
#     (lt.merge_knn with k=3), not hand-rolled pre-filtering logic
#
# setup:
#   pip install linktransformer
# first run downloads the embedding model from Hugging Face once (a few
# hundred MB), cached under ~/.cache afterwards -- same "first run is slow,
# that's normal" story as the Spark jars in spark_link_compare.py.

import os
import pandas as pd
import linktransformer as lt

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")

# a general-purpose sentence embedding model, not fine-tuned on facility
# names specifically -- good enough to demo the pipeline end to end.
# LinkTransformer also ships task-specific fine-tuned models on the
# dell-research-harvard HF org (see LINKING_LIBRARY_COMPARISON.md for the
# tradeoff of picking one of those over this general model instead).
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_unresolved_and_registry():
    unresolved = pd.read_csv(os.path.join(DATA_DIR, "facility_linkage_unresolved.csv"))
    manual_registry = pd.read_csv(os.path.join(DATA_DIR, "dhis2_manual_registry_fafan.csv"))
    return unresolved, manual_registry


def match_unresolved_org_units(top_n: int = 3) -> pd.DataFrame:
    """
    for every org unit left unresolved by the deterministic join
    (facility_linkage_unresolved.csv), finds its top_n closest name matches
    in the manually maintained regional registry (dhis2_manual_registry_
    fafan.csv), using embedding similarity instead of a shared id.

    uses lt.merge_knn, not lt.merge -- lt.merge only ever returns the
    single nearest match per row (its `merge_type` argument is deprecated
    as of linktransformer 0.1.14 and no longer controls how many
    candidates come back, it only validates key uniqueness now).
    merge_knn's `k` is the actual "how many candidates per row" knob,
    confirmed against the installed package source, not just its docs.
    """
    unresolved, manual_registry = load_unresolved_and_registry()

    matched = lt.merge_knn(
        unresolved,
        manual_registry,
        model=MODEL,
        on="name",
        k=top_n,
        suffixes=("_org_unit", "_manual_registry"),
    )

    # lt.merge_knn returns exactly top_n rows per org unit already, in
    # nearest-first order from the faiss search -- this sort is just
    # making that order explicit/guaranteed rather than relying on it
    matched = matched.sort_values(["id", "score"], ascending=[True, False])
    return matched.groupby("id").head(top_n)


def score_pair(name_a: str, name_b: str, model: str = MODEL) -> float:
    """
    single-pair convenience wrapper for spot-checking one match by hand --
    the equivalent of calling llm_match_facility() for one pair in the LLM
    scripts, minus the region argument (LinkTransformer scores the `on`
    column(s) you give it; pass a combined "name, region" string as name_a/
    name_b if region should factor into the score too).
    """
    pair_df = lt.evaluate_pairs(
        pd.DataFrame({"name_a": [name_a], "name_b": [name_b]}),
        model=model,
        left_on="name_a",
        right_on="name_b",
    )
    return float(pair_df["score"].iloc[0])


if __name__ == "__main__":
    results = match_unresolved_org_units(top_n=3)

    for org_unit_id, group in results.groupby("id"):
        first = group.iloc[0]
        name_col = "name_org_unit" if "name_org_unit" in group.columns else "name_x"
        print(f"\nUnresolved org unit: {first[name_col]!r}")
        for _, row in group.iterrows():
            match_col = "name_manual_registry" if "name_manual_registry" in row else "name_y"
            print(f"  vs {row[match_col]!r} -> score={row['score']:.3f}")

    out_path = os.path.join(DATA_DIR, "facility_linkage_linktransformer_matches.csv")
    results.to_csv(out_path, index=False)
    print(f"\nwrote {len(results)} candidate matches to {out_path}")
