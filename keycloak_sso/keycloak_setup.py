"""
Sets up a dedicated Keycloak realm and one client per service that can
actually speak OIDC, plus prints the client secrets you need to paste
into the docker run commands for each service.

Why a dedicated realm instead of reusing "master": master is Keycloak's
own admin realm. Putting demo users and clients in an admin realm works
for a quick test but is genuinely bad practice -- a leaked client secret
in the admin realm is a much bigger problem than one in a purpose-built
realm. This creates "nhdw" instead, and everything below lives there.

Run this once, after Keycloak is up (step 1 of NHDW_Demo_Commands_v2.txt),
before starting Grafana, MinIO, or the two oauth2-proxy gateways.

pip install requests
"""

import json
import os
import requests

KEYCLOAK = "http://localhost:8180"
ADMIN_USER = "username"
ADMIN_PASS = "password"
REALM = "nhdw"
DEMO_USER = "username"
DEMO_PASS = "password"


def get_admin_token():
    resp = requests.post(
        f"{KEYCLOAK}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASS,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def create_realm(token):
    headers = {"Authorization": f"Bearer {token}"}
    existing = requests.get(f"{KEYCLOAK}/admin/realms/{REALM}", headers=headers)
    if existing.status_code == 200:
        print(f"realm '{REALM}' already exists")
        return
    resp = requests.post(
        f"{KEYCLOAK}/admin/realms",
        headers=headers,
        json={"realm": REALM, "enabled": True},
    )
    resp.raise_for_status()
    print(f"created realm '{REALM}'")


def create_user(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(
        f"{KEYCLOAK}/admin/realms/{REALM}/users",
        headers=headers,
        json={
            "username": DEMO_USER,
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": DEMO_PASS, "temporary": False}],
        },
    )
    if resp.status_code == 409:
        print(f"user '{DEMO_USER}' already exists")
    else:
        resp.raise_for_status()
        print(f"created user '{DEMO_USER}'")


def create_client(token, client_id, redirect_uris):
    headers = {"Authorization": f"Bearer {token}"}
    existing = requests.get(
        f"{KEYCLOAK}/admin/realms/{REALM}/clients",
        headers=headers, params={"clientId": client_id},
    ).json()
    if existing:
        client_uuid = existing[0]["id"]
        print(f"client '{client_id}' already exists")
    else:
        resp = requests.post(
            f"{KEYCLOAK}/admin/realms/{REALM}/clients",
            headers=headers,
            json={
                "clientId": client_id,
                "enabled": True,
                "publicClient": False,
                "protocol": "openid-connect",
                "redirectUris": redirect_uris,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
            },
        )
        resp.raise_for_status()
        client_uuid = requests.get(
            f"{KEYCLOAK}/admin/realms/{REALM}/clients",
            headers=headers, params={"clientId": client_id},
        ).json()[0]["id"]
        print(f"created client '{client_id}'")

    secret = requests.get(
        f"{KEYCLOAK}/admin/realms/{REALM}/clients/{client_uuid}/client-secret",
        headers=headers,
    ).json()["value"]
    return secret


if __name__ == "__main__":
    token = get_admin_token()
    create_realm(token)
    create_user(token)

    secrets = {
        "grafana": create_client(token, "grafana", ["http://localhost:3000/login/generic_oauth"]),
        "minio": create_client(token, "minio", ["http://localhost:9001/oauth_callback"]),
        "postgres-gateway": create_client(token, "postgres-gateway", ["http://localhost:8091/oauth2/callback"]),
        "clickhouse-gateway": create_client(token, "clickhouse-gateway", ["http://localhost:8092/oauth2/callback"]),
        # added for the Kafka/Debezium + Superset integration --
        # see KEYCLOAK_SSO_SETUP.md steps 7/8 and superset/SUPERSET_SETUP.md
        "superset": create_client(token, "superset", ["http://localhost:8088/oauth-authorized/keycloak"]),
        "kafka-ui": create_client(token, "kafka-ui", ["http://localhost:8089/login/oauth2/code/keycloak"]),
        "kafka-connect-gateway": create_client(token, "kafka-connect-gateway", ["http://localhost:8093/oauth2/callback"]),
    }

    out_path = os.path.expanduser("~/habtech/keycloak_client_secrets.json")
    with open(out_path, "w") as f:
        json.dump(secrets, f, indent=2)

    print(f"\nwrote client secrets to {out_path}")
    print("realm:", REALM)
    print("demo login for every service below: username / password")
    for name, secret in secrets.items():
        print(f"  {name}: {secret}")
