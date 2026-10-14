# Apache Superset — dashboards on top of Postgres and ClickHouse

## Step 1, the Keycloak client

`keycloak_sso/keycloak_setup.py` already creates a `superset` client
(along with `kafka-ui` and `kafka-connect-gateway` for
`kafka_cdc/KAFKA_DEBEZIUM_SETUP.md`). Run it if this is the first time,
or rerun it if it's not — it's idempotent:

```
cd ~/habtech/keycloak_sso
python3 keycloak_setup.py
```

## Step 2, run Superset

```
SUPERSET_SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")
KEYCLOAK_SUPERSET_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['superset'])")

sudo docker network connect nhdw-net pg 2>/dev/null
sudo docker network connect nhdw-net clickhouse 2>/dev/null

sudo docker run -d --name superset --restart unless-stopped --network nhdw-net -p 8088:8088 \
  --add-host=keycloak.local:host-gateway \
  -e SUPERSET_SECRET_KEY=$SUPERSET_SECRET_KEY \
  -e KEYCLOAK_SUPERSET_SECRET=$KEYCLOAK_SUPERSET_SECRET \
  -v ~/habtech/superset/superset_config.py:/app/pythonpath/superset_config.py \
  apache/superset

sleep 15

# one-time bootstrap: an initial admin account for before Keycloak login
# is confirmed working, plus the db migration and default roles/examples
# Superset needs on a first boot -- normal steps for a fresh Superset
# container, not specific to this project
sudo docker exec -it superset superset fab create-admin \
  --username admin --firstname Admin --lastname User \
  --email admin@example.com --password password
sudo docker exec -it superset superset db upgrade
sudo docker exec -it superset superset init
```

`http://localhost:8088` — log in as `admin`/`password` first to confirm
it's up, then check `http://localhost:8088/login/keycloak` for the actual
Keycloak-gated login flow (demo login `username`/`password`, same as
everywhere else in this project).

## Step 3, connect the two warehouses

Install the drivers into the running container (or bake them into a
custom image if this needs to survive a container recreation):

```
sudo docker exec -it superset pip install psycopg2-binary clickhouse-connect
sudo docker restart superset
```

In Superset: **Settings → Database Connections → + Database**

| | Postgres | ClickHouse |
|---|---|---|
| SQLAlchemy URI | `postgresql://postgres:password@pg:5432/postgres` | `clickhousedb://username:password@clickhouse:8123/default` |
| What it's for | querying dbt's star schema directly (`dim_facility`, `fact_facility_infrastructure`, `fact_linkage_audit`) | fast rollup queries (`fact_facility_ch`, and `mfr_facilities_cdc` once Kafka/Debezium is wired in, see `kafka_cdc/KAFKA_DEBEZIUM_SETUP.md`) |

Both use the container hostnames (`pg`, `clickhouse`), not `localhost` —
Superset is asking from inside the `nhdw-net` docker network, same
container-vs-browser hostname distinction as everywhere else in this
project.

## Step 4, the one dashboard worth building for the demo

A chart on `fact_linkage_audit` (one row, but a good headline number) next
to a bar chart of `fact_facility_ch` grouped by `zone` — the deterministic
match rate next to the actual facility distribution it applies to. Add the
LinkTransformer-scored table
(`dbt_postgres_python/models/fact_linkage_scored.py`'s output) as a table
chart alongside it once that's built, to show the deterministic match
rate next to what the embedding-based matching adds on top of it.

## What's real here and what isn't

Superset speaks OIDC natively (Flask-AppBuilder's `AUTH_OAUTH`), same
tier as Grafana and MinIO in `KEYCLOAK_SSO_SETUP.md` — this is not a
gateway workaround like the Adminer/ClickHouse-play setup, it's a real
login button backed by Keycloak. The `admin`/`password` account from
`fab create-admin` still exists and still works after Keycloak is wired
in — that's intentional (a recovery path if Keycloak itself is down),
not a leftover to remove, but worth saying out loud in the demo the same
way the Postgres/ClickHouse CLI-password boundary is in
`KEYCLOAK_SSO_SETUP.md`.
