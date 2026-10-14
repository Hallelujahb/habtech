-- dim_geography: region/zone/woreda/PHCU hierarchy, sourced from DHIS2 org
-- units rather than the MFR's free-text region/zone/woreda fields, since the
-- DHIS2 tree is the authoritative, deduplicated hierarchy for this catchment

select distinct
    region_name,
    zone_name,
    woreda_name,
    phcu_name
from {{ ref('stg_org_units') }}
where region_name is not null
