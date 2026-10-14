# does the same linking job as the dbt fact_facility_infrastructure /
# fact_linkage_audit models, so the two can be compared directly on the same
# real-data task rather than two different jobs that happen to both use
# dataframes.
#
# this replaces the old fake-malaria join. the two real datasets are:
#   - master_facility_registry_clean.csv  (MFR: 1,332 facilities, Fafan Zone, Somali Region)
#   - org_units_clean.csv                 (DHIS2 org unit hierarchy, 492 units, same zone)
# they share a real key: mfr.dhis2_id == org_units.id. this script measures
# how much of the hierarchy resolves deterministically on that key, and
# writes the linked result plus the leftover unresolved units to MinIO.

import time
import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import col

HABTECH_HOME = os.environ.get("HABTECH_HOME", os.path.expanduser("~/habtech"))
DATA_DIR = os.path.join(HABTECH_HOME, "data_v2")

# without this block, Spark has no idea "s3a://" means "talk to MinIO" --
# that's the ClassNotFoundException: S3AFileSystem not found error. these
# two packages pull in the S3 filesystem implementation itself; the rest
# of the .config() calls point it at MinIO specifically (not real AWS)
# and paper over two known version-mismatch quirks between hadoop-aws and
# whatever Hadoop build ships inside this PySpark version -- both hit and
# fixed once already earlier in this project, same root cause each time.
spark = (
    SparkSession.builder.appName("nhdw_spark_link_compare")
    .master("local[*]")
    .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:3.4.1,software.amazon.awssdk:bundle:2.29.52")
    .config("spark.hadoop.fs.s3a.endpoint", "http://localhost:9000")
    .config("spark.hadoop.fs.s3a.access.key", "username")
    .config("spark.hadoop.fs.s3a.secret.key", "password")
    .config("spark.hadoop.fs.s3a.path.style.access", "true")
    .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
    .config("spark.hadoop.fs.s3a.aws.credentials.provider", "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")
    .config("spark.hadoop.fs.s3a.threads.keepalivetime", "60")
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
    .getOrCreate()
)
# first run downloads these jars once (a couple of minutes), cached after
# that -- see BENCHMARK_RESULTS-style notes elsewhere in this project on
# telling a real download from a stuck one, same story applies here

start = time.time()

mfr = spark.read.csv(f"{DATA_DIR}/master_facility_registry_clean.csv", header=True, inferSchema=True)
org_units = spark.read.csv(f"{DATA_DIR}/org_units_clean.csv", header=True, inferSchema=True)

linked = org_units.join(
    mfr,
    org_units["id"] == mfr["dhis2_id"],
    how="left"
).select(
    org_units["id"].alias("org_unit_id"),
    org_units["name"].alias("org_unit_name"),
    org_units["l2name"].alias("region"),
    org_units["l3name"].alias("zone"),
    mfr["id"].alias("facility_id"),
    mfr["name"].alias("mfr_facility_name"),
    mfr["number_of_inpatient_beds"].alias("inpatient_beds"),
    mfr["catchment_population"],
)

linked.createOrReplaceTempView("linked")

summary = spark.sql("""
    select
        region,
        count(*) as total_org_units,
        count(facility_id) as matched_deterministically,
        count(*) - count(facility_id) as unresolved_for_llm_matching
    from linked
    group by region
""")

summary.show(50, truncate=False)

unresolved = linked.filter(col("facility_id").isNull())

# write bronze (raw joined) and silver (unresolved-only, feeds the LLM step)
linked.write.mode("overwrite").parquet("s3a://bronze-zone/facility_linkage/")
unresolved.write.mode("overwrite").parquet("s3a://silver-zone/facility_linkage_unresolved/")

# gold: the aggregated, BI-ready table -- this is what a dashboard would
# actually query, not the raw per-facility join. without this write,
# gold-zone exists as an empty bucket with nothing giving it a reason to.
summary.write.mode("overwrite").parquet("s3a://gold-zone/facility_linkage_summary/")

elapsed = time.time() - start
print(f"spark link and aggregate finished in {elapsed:.2f} seconds")

spark.stop()
