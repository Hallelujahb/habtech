# registers the Debezium Postgres source connector against Kafka Connect's
# REST API. this is the one step that isn't a `docker run` -- Kafka
# Connect itself doesn't know what to capture until you POST it a config,
# same shape as keycloak_sso/keycloak_setup.py POSTing realm/client config
# to Keycloak's admin API rather than clicking through a UI.
#
# run this after Connect is up (step in KAFKA_DEBEZIUM_SETUP.md), before
# expecting any topics to exist.
#
# pip install requests

import json
import time
import requests

CONNECT_URL = "http://localhost:8083"
CONNECTOR_NAME = "nhdw-postgres-cdc"

CONNECTOR_CONFIG = {
    "name": CONNECTOR_NAME,
    "config": {
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "database.hostname": "pg",
        "database.port": "5432",
        "database.user": "postgres",
        "database.password": "password",
        "database.dbname": "postgres",
        # topics come out as "<topic.prefix>.<schema>.<table>", e.g.
        # nhdw.public.mfr_facilities -- this prefix, not database.dbname,
        # is what namespaces the topics, since one Postgres instance can
        # run more than one captured database
        "topic.prefix": "nhdw",
        # pgoutput is Postgres's own built-in logical replication output
        # plugin (since Postgres 10) -- no extra extension to install
        # inside the pg container, unlike the older wal2json approach
        "plugin.name": "pgoutput",
        "slot.name": "nhdw_debezium_slot",
        "publication.name": "nhdw_debezium_pub",
        # without this, Debezium's default (publication.autocreate.mode=
        # all_tables) creates a publication covering every table in the
        # database, not just the two below -- table.include.list would
        # still filter what gets forwarded, but the publication itself
        # would be tracking changes on tables we don't care about. this
        # keeps the publication itself scoped to match table.include.list
        "publication.autocreate.mode": "filtered",
        # only capture the two tables meltano actually loads -- capturing
        # every table in the database by default is rarely what you want
        "table.include.list": "public.mfr_facilities,public.org_units",
        # emit the row's full new state as plain json, not Kafka Connect's
        # own schema-wrapped Avro-like envelope -- much easier to read in
        # the demo and easier for ClickHouse's Kafka engine to consume
        "key.converter": "org.apache.kafka.connect.json.JsonConverter",
        "value.converter": "org.apache.kafka.connect.json.JsonConverter",
        "key.converter.schemas.enable": "false",
        "value.converter.schemas.enable": "false",
    },
}


def wait_for_connect(timeout_s=60):
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            if requests.get(CONNECT_URL).status_code == 200:
                return
        except requests.ConnectionError:
            pass
        print("waiting for Kafka Connect...")
        time.sleep(3)
    raise TimeoutError(f"Kafka Connect not reachable at {CONNECT_URL} after {timeout_s}s")


def register_connector():
    existing = requests.get(f"{CONNECT_URL}/connectors/{CONNECTOR_NAME}")
    if existing.status_code == 200:
        print(f"connector '{CONNECTOR_NAME}' already registered, updating config")
        resp = requests.put(
            f"{CONNECT_URL}/connectors/{CONNECTOR_NAME}/config",
            headers={"Content-Type": "application/json"},
            data=json.dumps(CONNECTOR_CONFIG["config"]),
        )
    else:
        resp = requests.post(
            f"{CONNECT_URL}/connectors",
            headers={"Content-Type": "application/json"},
            data=json.dumps(CONNECTOR_CONFIG),
        )
    resp.raise_for_status()
    print(f"registered '{CONNECTOR_NAME}', status:")
    print(json.dumps(resp.json(), indent=2))


def check_status():
    resp = requests.get(f"{CONNECT_URL}/connectors/{CONNECTOR_NAME}/status")
    resp.raise_for_status()
    status = resp.json()
    print(f"\nconnector state: {status['connector']['state']}")
    for task in status.get("tasks", []):
        print(f"  task {task['id']}: {task['state']}")
    return status


if __name__ == "__main__":
    wait_for_connect()
    register_connector()
    time.sleep(5)
    check_status()
    print(
        "\ntopics to expect: nhdw.public.mfr_facilities, nhdw.public.org_units\n"
        "list them with:\n"
        "  sudo docker exec -it kafka /opt/kafka/bin/kafka-topics.sh "
        "--bootstrap-server localhost:9092 --list"
    )
