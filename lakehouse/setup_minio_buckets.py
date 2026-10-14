# creates the three lakehouse buckets. spark_link_compare.py writes the
# actual data into bronze-zone/silver-zone itself once this step has run,
# so this script's only job is making sure the buckets exist first.

import os
from minio import Minio

client = Minio(
    "localhost:9000",
    access_key="username",
    secret_key="password",
    secure=False,
)

buckets = ["bronze-zone", "silver-zone", "gold-zone"]
for bucket in buckets:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"created bucket: {bucket}")
    else:
        print(f"bucket already exists: {bucket}")

print("done")
