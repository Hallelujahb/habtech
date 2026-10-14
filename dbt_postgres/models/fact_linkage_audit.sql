-- fact_linkage_audit: one row, the headline data-linking metric for the demo.
-- counts how many DHIS2 org units resolved to an MFR facility on the shared
-- dhis2_id key (deterministic linking) versus how many were left for the
-- LLM-assisted name-matching step to attempt.

with org as (
    select * from {{ ref('stg_org_units') }}
),

facility as (
    select * from {{ ref('stg_mfr_facilities') }}
)

select
    count(*) as total_org_units,
    count(f.dhis2_id) as matched_deterministically,
    count(*) - count(f.dhis2_id) as unresolved_for_llm_matching,
    round(count(f.dhis2_id)::numeric / nullif(count(*), 0) * 100, 1) as match_rate_pct
from org o
left join facility f on o.org_unit_id = f.dhis2_id
