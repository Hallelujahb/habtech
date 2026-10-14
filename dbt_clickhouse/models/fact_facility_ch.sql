-- ClickHouse fast-analytics rollup: facility infrastructure capacity by
-- region/zone, sourced from the same MFR data landed into ClickHouse for
-- OLAP-speed dashboard queries (Superset connects here)
--
-- column names here match the raw mfr_facilities_ch table exactly as
-- created by the CREATE TABLE in NHDW_Demo_Commands_v2.txt -- that table
-- has "type", not "facility_type", and no single "total_beds" column,
-- just three separate bed counts that need summing.
select
    region,
    zone,
    type as facility_type,
    count(*) as facility_count,
    sum(number_of_inpatient_beds + number_of_maternity_beds + number_of_emergency_beds) as total_beds,
    sum(catchment_population) as total_catchment_population,
    round(avg(number_of_inpatient_beds + number_of_maternity_beds + number_of_emergency_beds), 1) as avg_beds_per_facility
from default.mfr_facilities_ch
group by region, zone, type
