# LinkTransformer vs. the other real options — and why LinkTransformer stays

Checked before committing to LinkTransformer, since it's fair to ask whether
something else does this task better. Ruled out anything that's just a
wrapper around a general chat LLM (Gemini, GPT, Claude, an Ollama chat
model) — that's a different category of tool than what's compared here,
and the reason to move off it is exactly what's in
`llm_examples/`'s docstrings: no numeric score to threshold, no batch
nearest-neighbor search, an API call (or a full chat-model runtime) per
comparison instead of one embedding pass over the whole candidate pool.

The three real alternatives, all purpose-built for record linkage / entity
resolution the same way LinkTransformer is:

| | **LinkTransformer** | **Splink** | **Dedupe** | **Zingg** |
|---|---|---|---|---|
| Approach | transformer embeddings, nearest-neighbor | probabilistic (Fellegi-Sunter), no ML embeddings by default | active learning, logistic regression over string-similarity features | ML-based (embeddings + trained classifier), Spark-native |
| Maintainer | Dell lab, Harvard (Arora & Dell) | UK Ministry of Justice | independent (Dedupe.io) | independent, Apache-licensed |
| Handles spelling/script variation | strong — this is what embeddings are for | weak — needs comparison rules per field (Jaro-Winkler etc.) written by hand | moderate — learns from labeled examples | moderate-strong |
| Needs labeled training pairs | no, for the pretrained/general models used here | no | yes — the active-learning loop asks a human to label pairs as it goes | yes, for the ML path |
| Scale target | dataframe-sized (thousands–low millions) | built for very large (splink runs on DuckDB, Spark, or Postgres backends, scales to 100M+ rows) | small-to-medium | large, Spark-native |
| Runs offline / no API key | yes | yes | yes | yes |

## Why LinkTransformer for this task specifically

The two files being matched (`facility_linkage_unresolved.csv` and
`dhis2_manual_registry_fafan.csv`) are hand-entered by two different
regional systems, and Ethiopian facility names show up with real spelling
variation across sources in this dataset — see `Elbahay` vs `ceelbaxay`
in `org_units.csv` (Somali-language transliteration of the same place,
two different ways), or `Aliso health post` vs a slightly different
spelling of the same name in the manual registry. That's precisely the
case embeddings are good at and hand-written string-similarity rules
(Splink's default approach) are bad at: an edit-distance or Jaro-Winkler
rule doesn't know `Elbahay` and `ceelbaxay` are phonetically the same word
in two spellings, but a sentence embedding model, trained on enough text,
tends to place them close together in vector space anyway.

**Splink is the honest "better tool" answer for a different job.** If this
pipeline ever needs to link the full 59,917-row national MFR file (not the
1,332-row Fafan Zone subset used for the demo) against another
large source, Splink's purpose-built scale and its transparent,
auditable match-probability model (you can point to exactly which field
comparisons drove a match) are real advantages LinkTransformer doesn't
have out of the box. That's a real tradeoff worth naming rather than
picking one tool and pretending it wins on every axis.

**Dedupe and Zingg weren't chosen because they need labeled training
data** (Dedupe's active-learning loop, Zingg's classifier) before they're
useful — a real cost for a demo-scale project without an existing set of
confirmed facility-match pairs to train on. LinkTransformer's pretrained
general sentence-embedding models work out of the box with zero labeled
examples, which is why it's the one wired into
`linktransformer_examples/` right now. LinkTransformer also ships its own
collection of fine-tuned models on Hugging Face
(`dell-research-harvard` org) for specific record-linkage tasks and
languages — worth a look if the general `all-MiniLM-L6-v2` model's match
quality isn't good enough once tested against more real unresolved rows.

## What would change this answer

If the project later has: (a) a labeled set of confirmed facility matches
to train on, or (b) a national-scale linkage job instead of one zone —
that's the point to revisit Splink specifically, not before.
