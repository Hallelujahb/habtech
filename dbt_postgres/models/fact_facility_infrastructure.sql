-- fact_facility_infrastructure: grain is one row per MFR facility.
-- measures are infrastructure capacity (beds, rooms, catchment population).
-- linked_to_dhis2 flags whether this facility's dhis2_id resolved to a real
-- DHIS2 org unit (the deterministic half of the data-linking story; the
-- unresolved remainder is handled by the LLM matching step, see
-- llm_examples/llm_facility_matching.py and facility_linkage_unresolved.csv)

with facility as (
    select * from {{ ref('stg_mfr_facilities') }}
),

org as (
    select * from {{ ref('stg_org_units') }}
)

select
    f.facility_id,
    f.facility_name,
    f.facility_type,
    f.ownership,
    f.operational_status,
    f.catchment_population,
    f.year_opened_gregorian,
    f.beds_reported,
    f.inpatient_beds,
    f.maternity_beds,
    f.emergency_beds,
    f.opd_rooms,
    f.ipd_rooms,
    f.laboratory_rooms,
    f.imaging_rooms,
    f.mch_rooms,
    f.icu_rooms,
    (f.inpatient_beds + f.maternity_beds + f.emergency_beds) as total_beds,
    coalesce(o.region_name, f.region) as region,
    coalesce(o.zone_name, f.zone) as zone,
    coalesce(o.woreda_name, f.woreda) as woreda,
    (o.org_unit_id is not null) as linked_to_dhis2
from facility f
left join org o on f.dhis2_id = o.org_unit_id
