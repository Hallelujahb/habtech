-- staging: one row per facility as reported in the Master Facility Registry (MFR)
-- source table lands via meltano tap-csv -> target-postgres from
-- data_v2/master_facility_registry_clean.csv (cleaned by
-- data_cleaning/clean_facility_data.py: whitespace trimmed, leading-case
-- fixed, coordinates validated, year_opened converted to Gregorian,
-- beds_reported flag added -- see DATA_CLEANING_LOG.md)

select
    -- ::numeric::int instead of a direct ::int on every cast below: this
    -- tolerates a value arriving as either "9" or "9.0" without erroring.
    -- postgres's text->int cast rejects a decimal point outright even
    -- when the value is a whole number, but text->numeric->int handles
    -- both. belt-and-suspenders on top of the cleaning script now writing
    -- proper integers -- if a future data source formats numbers
    -- differently again, this won't break the whole model over it.
    id::numeric::bigint as facility_id,
    name as facility_name,
    type as facility_type,
    subtype as facility_subtype,
    ownership,
    status,
    operational_status,
    region,
    zone,
    zone_normalized,
    woreda,
    city,
    kebele,
    nullif(latitude, '')::float as latitude,
    nullif(longitude, '')::float as longitude,
    dhis2_id,
    ethiopian_national_facility_id,
    nullif(catchment_population, '')::numeric::int as catchment_population,
    nullif(year_opened_gregorian, '')::numeric::int as year_opened_gregorian,
    beds_reported::boolean as beds_reported,
    coalesce(nullif(number_of_inpatient_beds, '')::numeric::int, 0) as inpatient_beds,
    coalesce(nullif(number_of_maternity_beds, '')::numeric::int, 0) as maternity_beds,
    coalesce(nullif(number_of_emergency_beds, '')::numeric::int, 0) as emergency_beds,
    coalesce(nullif(number_of_opd_rooms, '')::numeric::int, 0) as opd_rooms,
    coalesce(nullif(number_of_ipd_rooms, '')::numeric::int, 0) as ipd_rooms,
    coalesce(nullif(number_of_laboratory_rooms, '')::numeric::int, 0) as laboratory_rooms,
    coalesce(nullif(number_of_imaging_rooms, '')::numeric::int, 0) as imaging_rooms,
    coalesce(nullif(number_of_mch_rooms, '')::numeric::int, 0) as mch_rooms,
    coalesce(nullif(number_of_icu_rooms, '')::numeric::int, 0) as icu_rooms
from public.mfr_facilities
