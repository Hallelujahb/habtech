# Kafka + Debezium — change data capture on top of the existing pipeline

## What this adds, and what it doesn't replace

Meltano (step 3 of the demo) still does the initial batch load of the three
CSVs into Postgres. Kafka/Debezium is a second, complementary path: once a
row in `mfr_facilities` or `org_units` changes — an edit, an insert, a
correction to a bad coordinate — Debezium picks that change up out of
Postgres's own write-ahead log within seconds and puts it on a Kafka topic,
without anyone re-running Meltano. This is the standard use case for CDC
(change data capture): keep a downstream system current without re-running
a full batch load every time.

Downstream here is ClickHouse, consuming the topics directly with its
built-in Kafka table engine (step 5 below) — so a row edited in Postgres
shows up in the OLAP layer Superset queries within seconds, not at the
next scheduled Meltano run.

## Step 0, Postgres has to actually support this

Debezium reads Postgres's write-ahead log via **logical replication**,
which is off by default. The `pg` container from
`NHDW_Demo_Commands_v2.txt` step 1 was never started with it on, so it
has to be recreated (this loses whatever is currently in it — reload with
Meltano afterwards, same as any other `docker rm -f` in this project):

```
sudo docker rm -f pg
sudo docker run --name pg --restart unless-stopped --network nhdw-net \
  -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres:16 \
  -c wal_level=logical -c max_replication_slots=4 -c max_wal_senders=4
```

Confirm it actually took (`logical`, not `replica`):

```
sudo docker exec -it pg psql -U postgres -c "SHOW wal_level;"
```

**Also required, and easy to miss:** Debezium needs each captured table to
have a real `PRIMARY KEY` (or an explicit `REPLICA IDENTITY`) — without
one, Postgres refuses to log `UPDATE`/`DELETE` events at all once a
publication is created on that table, and step 4's live demo silently
does nothing. Whether Meltano's `target-postgres` actually creates a
`PRIMARY KEY` constraint (versus just using `key_properties` for its own
upsert logic without a real constraint) isn't something to assume either
way — cheapest fix is to set this explicitly regardless of what Meltano
did, right after step 3's `meltano run`:

```
sudo docker exec -it pg psql -U postgres -c "ALTER TABLE mfr_facilities REPLICA IDENTITY FULL;"
sudo docker exec -it pg psql -U postgres -c "ALTER TABLE org_units REPLICA IDENTITY FULL;"
```

`REPLICA IDENTITY FULL` logs every column's old value on update/delete
(not just the primary key's), which is more WAL volume than the default
but is guaranteed to work whether or not a real primary key ended up on
these tables — the safe choice at this data size (hundreds to tens of
thousands of rows, not millions).

If `nhdw-net` doesn't exist yet: `sudo docker network create nhdw-net`
(same network used in `KEYCLOAK_SSO_SETUP.md`; Kafka, Connect, and
ClickHouse all need to be on it too, see below).

## Step 1, the Kafka broker (KRaft mode, no Zookeeper)

Using Confluent's Community-licensed image because its KRaft env-var
setup is the most stable/documented single-container pattern available;
nothing here is Confluent-cloud-specific, it's plain open-source Kafka
underneath.

```
sudo docker network connect nhdw-net pg 2>/dev/null

sudo docker run -d --name kafka --restart unless-stopped --network nhdw-net \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://:29092,CONTROLLER://:29093,PLAINTEXT_HOST://:9092 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092 \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:29093 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e CLUSTER_ID=$(sudo docker run --rm confluentinc/cp-kafka:7.7.0 kafka-storage random-uuid) \
  confluentinc/cp-kafka:7.7.0
sleep 15
```

Two listeners, same reason `keycloak.local` exists in
`KEYCLOAK_SSO_SETUP.md`: `kafka:29092` is what other containers (Connect,
ClickHouse) use to reach it *inside* the docker network, `localhost:9092`
is what a script or CLI running on the host machine uses. Getting this
backwards is the same class of bug the Keycloak doc already walked
through once (`DNS_PROBE_FINISHED_NXDOMAIN` / silently-broken discovery).

Confirm it's actually up:

```
sudo docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 --list
```

Should return empty (no topics yet), not an error.

## Step 2, Kafka Connect running Debezium

```
sudo docker run -d --name connect --restart unless-stopped --network nhdw-net \
  -p 8083:8083 \
  -e GROUP_ID=nhdw-connect \
  -e BOOTSTRAP_SERVERS=kafka:29092 \
  -e CONFIG_STORAGE_TOPIC=nhdw_connect_configs \
  -e OFFSET_STORAGE_TOPIC=nhdw_connect_offsets \
  -e STATUS_STORAGE_TOPIC=nhdw_connect_status \
  -e CONFIG_STORAGE_REPLICATION_FACTOR=1 \
  -e OFFSET_STORAGE_REPLICATION_FACTOR=1 \
  -e STATUS_STORAGE_REPLICATION_FACTOR=1 \
  -e CONNECT_REST_ADVERTISED_HOST_NAME=connect \
  quay.io/debezium/connect:3.0
sleep 20
```

Confirm the REST API is answering before registering anything against it:

```
curl -s http://localhost:8083/connectors
```

## Step 3, register the Postgres connector

```
pip install requests --break-system-packages
cd ~/habtech/kafka_cdc
python3 register_postgres_connector.py
```

This creates a Postgres publication + replication slot
(`nhdw_debezium_pub` / `nhdw_debezium_slot`) and starts streaming
`public.mfr_facilities` and `public.org_units`. First thing it does is
take a full snapshot of both tables (so the topics aren't empty even
before any new change happens), then switches to streaming ongoing
changes.

List the topics that appear:

```
sudo docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 --list
# nhdw.public.mfr_facilities, nhdw.public.org_units
```

Watch one live:

```
sudo docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic nhdw.public.mfr_facilities --from-beginning --max-messages 1
```

## Step 4, prove the "change data capture" part actually works

```
sudo docker exec -it pg psql -U postgres -c \
  "UPDATE mfr_facilities SET operational_status='Under Renovation' WHERE id='1006374';"

sudo docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 --topic nhdw.public.mfr_facilities --max-messages 1
```

That last message shows up within a couple seconds of the `UPDATE`, no
Meltano run in between — that's the actual thing to demo, live, in the
room.

## Step 5, ClickHouse consumes the topics directly

ClickHouse has a built-in `Kafka` table engine — no separate consumer
script needed, ClickHouse itself pulls from the topic. Debezium's
messages are a JSON envelope (`before`/`after`/`op`/`source` fields), so
this lands raw JSON first, then a materialized view unpacks the `after`
object (the row's new state) into the flat rollup table.

```
sudo docker network connect nhdw-net clickhouse 2>/dev/null

sudo docker exec -it clickhouse clickhouse-client --user username --password password --query "
CREATE TABLE default.mfr_facilities_kafka_raw (payload String)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:29092',
         kafka_topic_list = 'nhdw.public.mfr_facilities',
         kafka_group_name = 'clickhouse_nhdw',
         kafka_format = 'JSONAsString'"

sudo docker exec -it clickhouse clickhouse-client --user username --password password --query "
CREATE TABLE default.mfr_facilities_cdc (
    id String, name String, operational_status String, updated_at DateTime DEFAULT now()
) ENGINE = MergeTree ORDER BY id"

sudo docker exec -it clickhouse clickhouse-client --user username --password password --query "
CREATE MATERIALIZED VIEW default.mfr_facilities_cdc_mv TO default.mfr_facilities_cdc AS
SELECT
    JSONExtractString(payload, 'after', 'id') AS id,
    JSONExtractString(payload, 'after', 'name') AS name,
    JSONExtractString(payload, 'after', 'operational_status') AS operational_status
FROM default.mfr_facilities_kafka_raw
WHERE JSONExtractString(payload, 'op') != 'd'"
```

Repeat the `UPDATE` from step 4, then:

```
sudo docker exec -it clickhouse clickhouse-client --user username --password password --query \
  "SELECT * FROM default.mfr_facilities_cdc ORDER BY updated_at DESC LIMIT 5"
```

That row's new `operational_status` shows up here, sourced from the
Kafka topic, not from re-running dbt or Meltano — this is the actual
payoff of wiring CDC in: Superset's dashboards (see
`superset/SUPERSET_SETUP.md`), pointed at this table, go stale in
seconds instead of at the next scheduled batch load.

## Step 6, Kafka UI (optional, for actually looking at topics/consumers)

```
sudo docker run -d --name kafka-ui --restart unless-stopped --network nhdw-net -p 8089:8080 \
  -e KAFKA_CLUSTERS_0_NAME=nhdw \
  -e KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS=kafka:29092 \
  -e KAFKA_CLUSTERS_0_KAFKACONNECT_0_NAME=connect \
  -e KAFKA_CLUSTERS_0_KAFKACONNECT_0_ADDRESS=http://connect:8083 \
  provectuslabs/kafka-ui:latest
```

`http://localhost:8089` — browse topics, consumer groups, and the
Debezium connector's status in one place. Keycloak wiring for this one is
in `KEYCLOAK_SSO_SETUP.md`.

## Known limitations, said plainly

- **Single broker, no replication.** Fine for a demo, not how you'd run
  this for real — a production Kafka cluster needs at least 3 brokers so
  losing one doesn't lose data.
- **No schema registry.** Messages are plain JSON here, not Avro, so
  there's no enforced schema contract between producer and consumers.
  Adding Confluent Schema Registry (or Apicurio, the open-source
  alternative) is the next real step if this grows past a demo.
- **Deletes need `op != 'd'` handled explicitly** wherever the topic is
  consumed (the ClickHouse materialized view above does this) — a
  Debezium delete event still needs a real decision about whether the
  downstream table also deletes the row, soft-deletes it, or ignores it;
  this demo just excludes deletes from the rollup rather than picking one
  of those for you.
