# secondary, smaller use of the same library: the manually maintained
# regional registry (dhis2_manual_registry_fafan.csv) is hand-entered, so
# it's exactly the kind of file that ends up with near-duplicate rows --
# same facility typed in twice with a slightly different spelling. this
# clusters it and flags likely duplicates for a human to confirm, using
# LinkTransformer's dedup_rows, a one-function-call version of the same
# "cluster then keep/flag" idea used for the org-unit matching script.
#
# setup: pip install linktransformer  (same install as the matching script)

import os
import linktransformer as lt
import pandas as pd

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")
MODEL = "sentence-transformers/all-MiniLM-L6-v2"

if __name__ == "__main__":
    registry = pd.read_csv(os.path.join(DATA_DIR, "dhis2_manual_registry_fafan.csv"))

    # agglomerative clustering on embedding distance; "threshold" is a
    # similarity cutoff (0-1), "clustering linkage" and "metric" are
    # passed explicitly rather than left to default because the
    # library's cluster_params defaults shown in its docs are SLINK's,
    # not agglomerative's -- safer to be explicit than assume they carry
    # over when cluster_type is switched
    deduped = lt.dedup_rows(
        registry,
        model=MODEL,
        on="name",
        cluster_type="agglomerative",
        cluster_params={"threshold": 0.15, "clustering linkage": "average", "metric": "cosine"},
    )

    n_dropped = len(registry) - len(deduped)
    print(f"{len(registry)} rows in -> {len(deduped)} rows out ({n_dropped} flagged as likely duplicates)")

    out_path = os.path.join(DATA_DIR, "dhis2_manual_registry_fafan_deduped_v2.csv")
    deduped.to_csv(out_path, index=False)
    print(f"wrote deduplicated registry to {out_path}")
