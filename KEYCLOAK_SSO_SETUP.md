# Keycloak, wired into everything — what's real and what isn't

The honest version first, because it matters more than the commands:
**Grafana and MinIO both speak OIDC natively.** Point them at Keycloak and
they log in through it directly, no extra moving parts. **Postgres and
ClickHouse do not** — neither one's actual wire protocol (the thing
`psql` and `clickhouse-client` speak) supports OIDC login in the
open-source builds. That's not a gap in this setup, it's true of those
two databases generally.

So for those two, this wires up the part that's actually true to build:
a **web admin UI in front of each one, gated by Keycloak**, using
[oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy). What it
does NOT do is make `psql -U postgres` itself ask Keycloak for a login;
that command still uses the plain password from `CREDENTIALS.md`.

## The bug in the first version of this doc, and the actual fix

The first version pointed Keycloak-facing config at two different
hostnames: `localhost:8180` in the one spot that's browser-facing, and
`host.docker.internal:8180` everywhere else. That's backwards for MinIO
and oauth2-proxy specifically — both of them build a SINGLE issuer URL
from one setting, and that same URL ends up both fetched server-side
*and* used to construct the link your browser gets redirected to.
`host.docker.internal` only means anything inside a container; your
actual browser has no idea what it is, hence
`DNS_PROBE_FINISHED_NXDOMAIN`. That also explains MinIO showing no
Keycloak option at all — the discovery fetch was building broken
endpoint URLs from the start, not failing loudly, just quietly not
producing a working login button.

**The fix: one hostname, resolvable from both places.** Add it to your
machine's own hosts file once:

```
echo "127.0.0.1 keycloak.local" | sudo tee -a /etc/hosts
```

Now `keycloak.local:8180` resolves to Keycloak whether it's your browser
asking (hosts file) or a container asking (`--add-host=keycloak.local:host-gateway`,
added to every container below). Everything from here on uses
`keycloak.local`, nothing uses `host.docker.internal` or plain `localhost`
for anything Keycloak-related.

| service | how it's gated | logs in via Keycloak directly? |
|---|---|---|
| Grafana | native OIDC (`GF_AUTH_GENERIC_OAUTH_*`) | yes |
| MinIO console | native OIDC (`MINIO_IDENTITY_OPENID_*`) | yes |
| Superset | native OIDC (Flask-AppBuilder `AUTH_OAUTH`) | yes, see `superset/SUPERSET_SETUP.md` |
| Kafka UI | native OIDC (Spring Security OAuth2) | yes, see below |
| Postgres | Adminer web UI, behind oauth2-proxy | the web UI does, `psql` itself still doesn't |
| ClickHouse | built-in `/play` UI, behind oauth2-proxy | the web UI does, `clickhouse-client` itself still doesn't |
| Kafka Connect (Debezium) | its REST API, behind oauth2-proxy | the gated API endpoint does, the raw connector process still doesn't |
| Kafka broker itself | **not gated** — see "What doesn't get a Keycloak login, and why" below | no |
| Meltano | **nothing to gate** — see "What doesn't get a Keycloak login, and why" below | n/a |

## Step 1, create the realm, clients, and one demo login

```
pip install requests --break-system-packages
cd ~/habtech/keycloak_sso
python3 keycloak_setup.py
```

This prints seven client secrets (grafana, minio, postgres-gateway,
clickhouse-gateway, superset, kafka-ui, kafka-connect-gateway) and
writes them to `~/habtech/keycloak_client_secrets.json`. Demo login
everywhere below: `username` / `password`. It's idempotent — safe to
rerun any time, existing realm/clients/users are detected and skipped
rather than duplicated or errored on.

## Step 2, a docker network so the gateways can reach their backends

```
sudo docker network create nhdw-net
sudo docker network connect nhdw-net pg
sudo docker network connect nhdw-net clickhouse
```

## Step 3, recreate Grafana pointed at the `nhdw` realm

```
GRAFANA_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['grafana'])")

sudo docker rm -f grafana
sudo docker run -d --name grafana --restart unless-stopped -p 3000:3000 \
  --add-host=keycloak.local:host-gateway \
  -e GF_SECURITY_ADMIN_USER=username -e GF_SECURITY_ADMIN_PASSWORD=password \
  -e GF_AUTH_GENERIC_OAUTH_ENABLED=true \
  -e GF_AUTH_GENERIC_OAUTH_NAME=Keycloak \
  -e GF_AUTH_GENERIC_OAUTH_CLIENT_ID=grafana \
  -e GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET=$GRAFANA_SECRET \
  -e GF_AUTH_GENERIC_OAUTH_SCOPES="openid email profile" \
  -e GF_AUTH_GENERIC_OAUTH_AUTH_URL=http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/auth \
  -e GF_AUTH_GENERIC_OAUTH_TOKEN_URL=http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/token \
  -e GF_AUTH_GENERIC_OAUTH_API_URL=http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/userinfo \
  -e GF_AUTH_GENERIC_OAUTH_ALLOW_SIGN_UP=true \
  grafana/grafana
```

Check the actual login screen, not the dashboard you're already signed
into: open a private/incognito window to `http://localhost:3000/login`
— that's the only way to actually see the button, since a normal window
reuses your existing admin session and skips straight to the dashboard,
which is almost certainly why it looked "not connected" before. You
should see "Sign in with Keycloak" there.

If not: `sudo docker logs grafana 2>&1 | grep -i oauth`

## Step 4, recreate MinIO with native OIDC

```
MINIO_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['minio'])")

sudo docker rm -f minio
sudo docker run -d --name minio --restart unless-stopped --network nhdw-net -p 9000:9000 -p 9001:9001 \
  --add-host=keycloak.local:host-gateway \
  -e "MINIO_ROOT_USER=username" -e "MINIO_ROOT_PASSWORD=password" \
  -e "MINIO_PROMETHEUS_AUTH_TYPE=public" \
  -e "MINIO_IDENTITY_OPENID_CONFIG_URL=http://keycloak.local:8180/realms/nhdw/.well-known/openid-configuration" \
  -e "MINIO_IDENTITY_OPENID_CLIENT_ID=minio" \
  -e "MINIO_IDENTITY_OPENID_CLIENT_SECRET=$MINIO_SECRET" \
  -e "MINIO_IDENTITY_OPENID_SCOPES=openid" \
  -e "MINIO_IDENTITY_OPENID_REDIRECT_URI=http://localhost:9001/oauth_callback" \
  -e "MINIO_IDENTITY_OPENID_DISPLAY_NAME=Keycloak" \
  minio/minio server /data --console-address ":9001"

sleep 5
python3 ~/habtech/lakehouse/setup_minio_buckets.py
```

Confirm the config was actually read before checking the browser:

```
sudo docker logs minio 2>&1 | grep -i openid
```

If that shows no errors, refresh `http://localhost:9001/login` (hard
refresh, `Ctrl+Shift+R` — MinIO's console is a cached JS bundle and can
show a stale login page otherwise). You should now see a second login
option below the username/password fields, labeled "Keycloak".

## Step 5, Adminer (Postgres web UI) behind oauth2-proxy

```
PG_GW_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['postgres-gateway'])")

sudo docker rm -f adminer oauth2-proxy-pg 2>/dev/null
sudo docker run -d --name adminer --restart unless-stopped --network nhdw-net adminer

sudo docker run -d --name oauth2-proxy-pg --restart unless-stopped --network nhdw-net -p 8091:4180 -p 44181:44181 \
  --add-host=keycloak.local:host-gateway \
  quay.io/oauth2-proxy/oauth2-proxy \
  --provider=oidc \
  --oidc-issuer-url=http://keycloak.local:8180/realms/nhdw \
  --client-id=postgres-gateway \
  --client-secret=$PG_GW_SECRET \
  --redirect-url=http://localhost:8091/oauth2/callback \
  --upstream=http://adminer:8080 \
  --http-address=0.0.0.0:4180 \
  --metrics-address=0.0.0.0:44181 \
  --email-domain=* \
  --cookie-secret=$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(16)).decode())") \
  --cookie-secure=false \
  --insecure-oidc-allow-unverified-email=true
```

`http://localhost:8091` now asks for a Keycloak login before showing
Adminer (server field: `pg`, username `postgres`, password `password`).

## Step 6, ClickHouse's `/play` UI behind oauth2-proxy

```
CH_GW_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['clickhouse-gateway'])")

sudo docker rm -f oauth2-proxy-ch 2>/dev/null
sudo docker run -d --name oauth2-proxy-ch --restart unless-stopped --network nhdw-net -p 8092:4180 -p 44182:44182 \
  --add-host=keycloak.local:host-gateway \
  quay.io/oauth2-proxy/oauth2-proxy \
  --provider=oidc \
  --oidc-issuer-url=http://keycloak.local:8180/realms/nhdw \
  --client-id=clickhouse-gateway \
  --client-secret=$CH_GW_SECRET \
  --redirect-url=http://localhost:8092/oauth2/callback \
  --upstream=http://clickhouse:8123 \
  --http-address=0.0.0.0:4180 \
  --metrics-address=0.0.0.0:44182 \
  --email-domain=* \
  --cookie-secret=$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(16)).decode())") \
  --cookie-secure=false \
  --insecure-oidc-allow-unverified-email=true
```

`http://localhost:8092/play` now asks for a Keycloak login first.

## Step 7, Kafka UI, native OIDC

Kafka UI (Provectus) supports Keycloak login the same tier as Grafana —
real OIDC, not a gateway. `keycloak_setup.py` already creates the
`kafka-ui` client (step 1 above); recreate the container from
`kafka_cdc/KAFKA_DEBEZIUM_SETUP.md` step 6 with:

```
KAFKA_UI_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['kafka-ui'])")

sudo docker rm -f kafka-ui
sudo docker run -d --name kafka-ui --restart unless-stopped --network nhdw-net -p 8089:8080 \
  --add-host=keycloak.local:host-gateway \
  -e KAFKA_CLUSTERS_0_NAME=nhdw \
  -e KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS=kafka:29092 \
  -e KAFKA_CLUSTERS_0_KAFKACONNECT_0_NAME=connect \
  -e KAFKA_CLUSTERS_0_KAFKACONNECT_0_ADDRESS=http://connect:8083 \
  -e AUTH_TYPE=OAUTH2 \
  -e SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_CLIENT-ID=kafka-ui \
  -e SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_CLIENT-SECRET=$KAFKA_UI_SECRET \
  -e SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_SCOPE=openid,email,profile \
  -e SPRING_SECURITY_OAUTH2_CLIENT_PROVIDER_KEYCLOAK_ISSUER-URI=http://keycloak.local:8180/realms/nhdw \
  provectuslabs/kafka-ui:latest
```

## Step 8, Kafka Connect's REST API behind oauth2-proxy

Connect's REST API (where `kafka_cdc/register_postgres_connector.py`
posts the Debezium config, and where the connector's live status lives)
has no login UI of its own — same category as Postgres and ClickHouse,
gated with the same oauth2-proxy pattern as steps 5/6 above:

```
KAFKA_CONNECT_GW_SECRET=$(python3 -c "import json; print(json.load(open('$HOME/habtech/keycloak_client_secrets.json'))['kafka-connect-gateway'])")

sudo docker run -d --name oauth2-proxy-connect --restart unless-stopped --network nhdw-net -p 8093:4180 -p 44183:44183 \
  --add-host=keycloak.local:host-gateway \
  quay.io/oauth2-proxy/oauth2-proxy \
  --provider=oidc \
  --oidc-issuer-url=http://keycloak.local:8180/realms/nhdw \
  --client-id=kafka-connect-gateway \
  --client-secret=$KAFKA_CONNECT_GW_SECRET \
  --redirect-url=http://localhost:8093/oauth2/callback \
  --upstream=http://connect:8083 \
  --http-address=0.0.0.0:4180 \
  --metrics-address=0.0.0.0:44183 \
  --email-domain=* \
  --cookie-secret=$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(16)).decode())") \
  --cookie-secure=false \
  --insecure-oidc-allow-unverified-email=true
```

`http://localhost:8093/connectors` now asks for a Keycloak login before
showing what Connect's REST API would show directly.

## What doesn't get a Keycloak login, and why

Two real gaps, said plainly instead of glossed over:

**The Kafka broker itself isn't gated.** Apache Kafka *can* authenticate
against an OIDC provider like Keycloak — the `SASL_OAUTHBEARER`
mechanism (KIP-768) exists and is real, not vaporware. It's left out of
this setup because it needs a token endpoint URL baked into every
client's connection config (Kafka Connect, ClickHouse's Kafka table
engine, `kafka-console-consumer`, any future producer/consumer), a
listener reconfigured for SASL_SSL, and realistically TLS in front of it
too since OAUTHBEARER over plaintext defeats the point — that's a
half-day of its own work, not a follow-on step to the pattern above,
and it's genuinely optional for a local demo where nothing routes
outside `nhdw-net`. Worth naming as the real next step if this ever runs
somewhere multi-tenant.

**Meltano has nothing to gate.** Meltano's web UI was deprecated in
2.12 and fully removed in Meltano 3.0 — the project runs entirely as
CLI commands (`meltano run`, `meltano config set`, etc.), no
long-running service with a login screen exists to put Keycloak in front
of. If a scheduler gets added later (Meltano's own docs point at Airflow
or Dagster for this now that its own UI is gone), that scheduler's
webserver — not Meltano itself — would be the thing to wire into
Keycloak, the same oauth2-proxy pattern as Adminer/ClickHouse-play above
works for Airflow's webserver too.

## If a browser tab still tries to reach `host.docker.internal`

That means it's a leftover redirect from before this fix — a stale
cookie or a bookmarked callback URL from the earlier broken config.
Clear cookies for `localhost` (or just use a private window) and start
the login again from `http://localhost:9001/login` /
`http://localhost:3000/login`, not from a URL still sitting in the
address bar from the last attempt.

## What to say in the room

"Seven ways in now — Grafana, MinIO, Superset, Kafka UI, and the three
database/connector web UIs — all sit behind the same Keycloak login, one
realm, one place to add or revoke a person. The pieces without a browser
login of their own — Postgres and ClickHouse's own command-line clients,
and the Kafka broker's client protocol — still use local credentials,
and that's a real, honest boundary, not a gap we missed: those wire
protocols don't speak OIDC, full stop. Meltano has no login surface at
all to gate — its web UI was removed in version 3, it's CLI-only now."
