-- staging: one row per DHIS2 organisation unit (facility-level leaf nodes and
-- their parent hierarchy). source table lands via meltano tap-csv ->
-- target-postgres from data_v2/org_units_clean.csv (whitespace trimmed,
-- zone_normalized added -- see DATA_CLEANING_LOG.md)

select
    id as org_unit_id,
    name as org_unit_name,
    level as org_level,
    parentid as parent_org_unit_id,
    l1name as country_name,
    l2name as region_name,
    l3name as zone_name,
    zone_normalized,
    l4name as woreda_name,
    l5name as phcu_name,
    l6name as facility_name_dhis2,
    leaf as is_leaf
from public.org_units
