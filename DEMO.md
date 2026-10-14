# NHDW Demo Script
**How to present this so it lands.** Companion to `NHDW_Demo_Commands_v3.txt` (the exact commands) and `NHDW_Complete_System_Overview.pdf` (the full written record). This file is the *narrative* — what to say, in what order, and how to handle the parts that aren't finished without losing the room.

Total runtime: **~30 min demo + 10 min Q&A**. Cut to ~15 min using the "if you're short on time" markers below.

---

## 0. The day before — prep checklist

- [ ] Run step 1 of the commands file fresh, confirm all containers healthy (`docker ps`, nothing restarting in a loop)
- [ ] Re-run steps 2–9 once end to end so the numbers on screen match the numbers you say out loud
- [ ] Have `NHDW_Complete_System_Overview.pdf` section 4 (the real-vs-not table) open in a tab — you will point at it on purpose, not defensively
- [ ] Confirm Prometheus targets page shows both targets green (`localhost:9090/targets`)
- [ ] Log into Grafana with plain admin credentials beforehand — **do not** attempt the live Keycloak OAuth flow in front of the room (see §4)
- [ ] Pre-stage a terminal tab per major step so you're not retyping paths live
- [ ] Have one row of `master_facility_registry.csv` memorized to hand-edit live during the CDC demo

---

## 1. Open with the one paragraph (30 seconds, memorize this)

Don't open with a tool list. Open with the claim:

> "This is a real health-facility data warehouse for one zone, built on the actual open-source data-engineering stack — ingestion, transformation, two storage engines, AI-assisted record linking, real-time change capture, BI, SSO, and monitoring, all demonstrated live. On top of that, I validated the same linking logic at national scale using data already in hand, found and am now investigating an 8,800-record gap the original pipeline never surfaced, and documented the path from this laptop demo to a real deployment."

Everything after this is proving that paragraph, piece by piece. That's the whole demo.

---

## 2. Act 1 — the live Fafan pipeline (~12 min)

This is the part that's fully real and fully live. Walk it in the order data actually flows, not the order it's convenient to talk about.

**Cleaning → the credibility beat.** Run the cleaning script, show the log. Say the numbers, don't paraphrase them:
> "2,522 cells trimmed and normalized. Dates converted out of the Ethiopian calendar. Coordinates validated against Ethiopia's real bounding box — anything outside it gets flagged, not silently kept."

**Ingest + dbt → the join.** This is the number the whole demo hangs on. Say it exactly once, clearly, and let it sit:
> "Every org unit and every MFR facility feeds one join: `org_units.id == mfr.dhis2_id`. 340 of 492 org units — 69% — resolve automatically. The other 152 have no shared ID, only a name."

Query `fact_linkage_audit` live. Don't just say the number — show the table producing it.

**Spark → the "same join, different tool" beat.** This is a credibility signal, not a new fact: it proves the 69% isn't an artifact of one tool's SQL quirks. One sentence: "Same join, done independently in Spark, writing bronze/silver/gold to MinIO — same number comes out."

**LinkTransformer → the AI beat.** This is your best "wow" moment because it visibly resolves the 152 the deterministic join couldn't. Run it live if time allows; show 3–4 actual matched pairs on screen (real facility names, real similarity scores). This is more convincing than any slide.

**ClickHouse → speed.** Run the same-shape query against ClickHouse right after Postgres, back to back, so the room feels the columnar speed difference rather than being told about it.

**Kafka/Debezium CDC → the best live moment in the whole demo.** Edit one row in the pre-staged terminal (`UPDATE mfr_facilities SET ... WHERE id = ...`), then flip to the Kafka topic consumer or the ClickHouse CDC table and watch the change land in seconds. This is the single most impressive 20 seconds of the demo — slow down here, don't rush past it.

**Grafana/Prometheus → the "and it's being watched" close.** Show the dashboards already populated from everything above. If you want a second live moment and have time: `docker stop <container>` on something non-critical, and watch the panel go red in real time.

*If you're short on time:* cut Spark and ClickHouse-speed to one sentence each; never cut the AI-linking or CDC live moments — those are what people remember.

---

## 3. Act 2 — the national validation story (~6 min)

This is a genuinely good story and it's underused if you just read out numbers. Tell it as a story:

> "After building the Fafan pipeline, I noticed something: the MFR file's `dhis2_id` column and the DHIS2 sheet's `uid` column share the same ID space *nationally*, not just in this one zone. So I asked — does the deterministic join that resolves 69% in Fafan hold up at national scale, using data already sitting on disk?"

Then the numbers, in this order — build, don't front-load:

1. **The headline:** "29,016 MFR facilities carry a `dhis2_id`. 28,383 of them — 97.8% — match a `uid` in the national DHIS2 sheet. Ten seconds, pandas and openpyxl, nothing else."
2. **The forward gap:** "633 facilities have a `dhis2_id` that matched nothing — typos, retired records, edits on one side that never made it to the other. I ran those through LinkTransformer against the full 37,177-row national sheet."
3. **The reverse gap — this is the interesting one:** "8,796 DHIS2 records have *no* MFR facility pointing to them at all. Same problem, other direction. And the region breakdowns of both gaps line up closely — Oromia and Amhara dominate both, in similar proportions. That's a real signal these are the same underlying gap viewed from two sides, not two unrelated problems."

**On the 0.75 similarity cutoff — say this if asked, and it's fine to say it before being asked:**
> "Below 0.75, a match is closer to a coin flip than a real signal. Keeping low-confidence guesses would add review burden without adding real matches, so they're dropped rather than shown as a maybe. That's a tuned judgment call, not an arbitrary number, and I'm comfortable defending the specific value if asked."

---

## 4. Act 3 — the infra-as-code layer (~6 min)

**The framing that makes this land instead of feeling like an apology:** you are not presenting four half-finished side projects. You are presenting the answer to one question a good reviewer will ask about *any* of this: "fine, but how does it get deployed?" Lead with that framing, not with "these aren't live yet."

Say the real-vs-not line **before** anyone else has to ask it — that's what makes it read as rigor instead of a gap:

> "Everything I've shown so far runs by hand, in order, on one machine. That's fine for a demo, dangerous for anything real. The `infra/` folder is the answer to that — and I want to be precise about what's validated versus what's live, because that distinction matters."

Then, live on screen, in this order:

1. **`helm lint` + `helm template`** — "This renders the exact Kubernetes manifests a real cluster would run. StatefulSets for Postgres and ClickHouse specifically — not Deployments — because a StatefulSet keeps the same disk attached across a restart. That's the direct fix for a real problem this project hit: the Keycloak crash-restart that silently lost realm data was exactly this class of bug."
2. **`ansible-playbook site.yml --syntax-check`**, then the local `--check --diff` dry run — "Same deployment, no cluster required — this is the bare-metal path, one server or a small fleet. Every role is idempotent: rerun it after a crash and it only fixes what's actually broken, unlike the manual `docker rm -f` at the top of the runbook."
3. **The Airflow DAG import check**, then talk through the dependency graph on screen — "Spark's comparison and the AI matching only depend on ingestion, not on each other — Airflow runs them in parallel automatically. A shell script can't do that without me manually managing background processes."
4. **The GitHub Actions workflow** — either show a real green checkmark on a past commit, or run `act` locally — "Every push touching the dbt models or the Meltano config re-runs ingest, transform, and test automatically. Nobody finds out something broke by discovering it live in a room like this one."

Close Act 3 with the sentence that ties Helm and Ansible together, since someone will otherwise ask "why both":
> "Kubernetes and bare metal aren't competing choices here — they're the same deployment problem solved for two different environments. A real organization typically ends up with both, not one instead of the other, depending on what a given site actually has available."

---

## 5. The Keycloak issue — how to handle it live (~1–2 min, only if it comes up or you choose to volunteer it)

Do **not** attempt the live OAuth redirect-to-login flow and hope it works. You already know it's broken. Instead:

> "SSO wiring is real — Grafana, MinIO, Superset, Kafka UI all point at Keycloak, and I can show you the login redirect as visual proof the integration exists." *(click the button, show the redirect happen)* "I won't complete the flow live, because the token exchange is currently broken — Keycloak's dev container has no persistent volume for its own realm data in the manual setup, so a restart can silently lose that config even though the container looks healthy. I know exactly why, and I've already written the fix: the Ansible Keycloak role mounts a named volume for exactly this — I just haven't applied it to this specific demo box yet."

This turns a bug into a demonstration that you diagnosed a real infra problem and already designed the correct fix — which is a *stronger* signal than if OAuth had just worked quietly.

---

## 6. Anticipated questions (have these loaded, don't read them verbatim)

**"Why two separate pipelines instead of one?"**
Pipeline 1 proves the full stack works end to end on real data, at zone scale, live. Pipeline 2 asks a narrower, sharper question — does the same ID logic hold at 60x the scale — using data already on disk, no infra required. Keeping them separate means neither one's complexity slows the other down.

**"Why LinkTransformer over an LLM for the name matching?"**
It's a record-linkage library, not a general chat model — it returns a numeric similarity score instead of free text you have to parse, it's local, no API key, no rate limit. (If pushed further: mention Gemini and Ollama were both built and tested too — `LINKING_LIBRARY_COMPARISON.md` has the full comparison — but LinkTransformer is the one to lead with.)

**"What actually breaks the dbt Python model?"**
A real, specific pandas/numpy version conflict between the AI-matching libraries and the older `dbt-postgres-python` adapter — not vague "compatibility issues." Name it precisely if asked; vague answers read as not understanding your own blocker.

**"Is this deployed anywhere real?"**
No — be direct. "The chart and playbook are validated and correct, not yet pointed at a live cluster or server. That's the honest state, and it's a smaller gap than it sounds — the actual pipeline logic is proven live; what's left is pointing already-correct infra code at a target."

**"What data privacy exposure does the AI matching have?"**
Only a facility name and region are ever sent anywhere, and that's documented precisely in `DATA_GOVERNANCE_NOTE.md` — reference it directly rather than reconstructing the policy from memory in the room.

---

## 7. Closing line

> "So: one zone, fully real, fully live, on the actual stack. The same core logic validated at national scale, with a real gap found and a real next step defined. And a documented, syntactically-validated path from this laptop to production — Kubernetes or bare metal, orchestrated instead of manual, tested on every change instead of discovered broken in a room like this one."

Then stop talking and take questions. Don't keep selling after the close line — it undercuts it.
