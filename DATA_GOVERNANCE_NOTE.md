# Why sending facility names to an LLM is fine here

A fair question to expect in the demo: "you're sending government data to
Google's API — is that okay?" Here's the honest answer, worth having ready.

## What actually leaves the network

Look at the prompt built in `llm_facility_matching.py` — exactly two short
fields per call:
- a facility name (e.g. "Al-fatahi Medium clinic")
- a region/zone name (e.g. "Fafan Zone")

That's it. Not beds, not catchment population, not lat/long, not
`ethiopian_national_facility_id`, not the facility's phone number or
owner's name — none of the columns that exist in the MFR file ever reach
the LLM. The pre-filtering step (`top_candidates`) also runs entirely
locally, so most of the ~460-row candidate pool is never sent anywhere;
only the top 3 candidates per unresolved unit get an actual API call.

## Why that specific data is low-risk

A health facility's name and its general administrative location are not
private information about a person — they're the same kind of thing
that's already on the building's sign, in DHIS2's own public metadata
model, and in any public health facility directory. There's no patient
data, no individual's name, no financial data, and no unique national
facility ID in what gets sent. This is closer to typing a business name
into a maps app than to handling a medical record.

## What would make this NOT fine, and how to check for it

If a future version of this pipeline ever needs to send anything beyond
name + region to an external LLM API — individual-level records,
addresses tied to a person, financial or clinical fields — that's a real
conversation to have with whoever owns the data-sharing policy for the
source system first, not a call to make unilaterally in a script. Good
practice for that conversation:
- data minimization: only ever send the smallest fields needed for the
  specific judgment being asked
- log every LLM call made against government data, so there's an audit
  trail of exactly what was sent and when
- for stricter requirements, the same matching approach works with a
  self-hosted open-weights model instead of a hosted API — same prompt,
  no data leaving your own infrastructure at all

For this specific task — resolving whether two facility name strings
describe the same real place — the field-level exposure above is the
actual, checkable answer, not an assumption.
