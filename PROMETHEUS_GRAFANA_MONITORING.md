# Prometheus and Grafana, watching every real service in the stack

Prometheus and cAdvisor both start in step 1 of `NHDW_Demo_Commands_v2.txt`
now, so container-level oversight (cpu, memory, alive/dead, for every
single container) exists from the start, not as a later add-on. This doc
covers the rest: wiring Grafana to actually read from Prometheus, and
giving Prometheus real application-level metrics for Postgres,
ClickHouse, MinIO, and Keycloak, not just container-level ones.

## Part one, Grafana reading from Prometheus

```
curl -s -X POST -H "Content-Type: application/json" \
  -u username:password \
  http://localhost:3000/api/datasources \
  -d '{"name": "Prometheus", "type": "prometheus", "url": "http://host.docker.internal:9090", "access": "proxy", "isDefault": true}'
```

If this returns a message mentioning `host.docker.internal`, recreate
Grafana with `--add-host=host.docker.internal:host-gateway`, already
included in step 1's Grafana command.

## Part two, what's actually being scraped

`monitoring/prometheus.yml` has one job per real metrics source:

| job | what it covers | how |
|---|---|---|
| `cadvisor` | cpu/memory/alive for every container | already running, no extra setup |
| `postgres` | query stats, connections, table sizes | `postgres_exporter` container, see KEYCLOAK_SSO_SETUP.md step 5 area or run standalone (below) |
| `clickhouse` | query stats, merges, memory | ClickHouse's own built-in Prometheus endpoint, enabled via `monitoring/clickhouse_prometheus.xml` mounted at container start |
| `minio` | requests, storage usage, uptime | MinIO's own built-in `/minio/v2/metrics/cluster` endpoint |
| `keycloak` | logins, token issuance | Keycloak's own metrics, enabled via `--metrics-enabled=true` |
| `oauth2-proxy-*` | login attempts through each gateway | oauth2-proxy's own `--metrics-address` flag |

Postgres doesn't expose Prometheus metrics on its own, so it needs the
one real exporter in this list:

```
sudo docker run -d --name postgres-exporter --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -e DATA_SOURCE_NAME="postgresql://postgres:password@host.docker.internal:5432/postgres?sslmode=disable" \
  -p 9187:9187 \
  quay.io/prometheuscommunity/postgres-exporter
```

ClickHouse needs its container recreated once with the mounted config
(this is already reflected in step 1's clickhouse command in
`NHDW_Demo_Commands_v2.txt`; if you started it before that update, rerun
step 1's clickhouse block):

```
sudo docker rm -f clickhouse
sudo docker run -d --name clickhouse --restart unless-stopped -p 8123:8123 -p 9363:9363 \
  -e CLICKHOUSE_USER=username -e CLICKHOUSE_PASSWORD=password \
  -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
  -v ~/habtech/monitoring/clickhouse_prometheus.xml:/etc/clickhouse-server/config.d/prometheus.xml \
  clickhouse/clickhouse-server
```

Confirm everything landed: `http://localhost:9090/targets` should show
every job above green. Keycloak's exact metrics port has moved between
versions — check `docker logs keycloak` for a line like "Management
interface listening on ... 9000" and adjust the `keycloak` job's target
port in `prometheus.yml` if it doesn't say 9002 (the port this project
publishes it on, see KEYCLOAK_SSO_SETUP.md).

## The down-detection demo

```
time() - container_last_seen{name=~"pg|clickhouse|minio"}
```

Paste that into Grafana's Explore view against the Prometheus data
source. Every line stays near zero while everything is up. Then:

```
sudo docker stop pg
```

Refresh the panel — the `pg` line climbs steadily while the others stay
flat. Bring it back with `sudo docker start pg`, the line drops back to
near zero the moment cAdvisor sees it again.

## What to say in the room

Run the stop command live, don't pre-record it: "I'm stopping the
Postgres container right now, watch this line." Then: "This is the
difference between a dashboard that shows numbers and one that would
actually tell someone a service went down before they found out by
trying to use it and hitting an error."

Be honest about the boundary: this shows whether the infrastructure is
alive and, now, some of what it's doing — not whether the data inside it
is correct. A container can be perfectly healthy and still be serving
bad data. That's a different question this setup doesn't answer, worth
saying if asked.
