select distinct
    facility_id,
    facility_name,
    facility_type,
    facility_subtype,
    ownership,
    status,
    operational_status,
    region,
    zone,
    woreda,
    dhis2_id
from {{ ref('stg_mfr_facilities') }}
