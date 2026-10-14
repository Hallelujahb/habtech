# mounted into the Superset container at
# /app/pythonpath/superset_config.py -- Superset reads this file on boot
# for anything not covered by env vars. Two jobs here: turn on Keycloak
# OIDC login (Flask-AppBuilder's OAUTH_PROVIDERS, same idea as Grafana's
# GF_AUTH_GENERIC_OAUTH_* env vars in KEYCLOAK_SSO_SETUP.md, just
# configured in Python instead of env vars because that's how FAB expects
# it), and point Superset at a secret key + the two warehouses it queries.

import os

# --- Keycloak OIDC -----------------------------------------------------
# same "one hostname, resolvable from both browser and containers" fix as
# every other Keycloak-gated service in this project -- see
# KEYCLOAK_SSO_SETUP.md for why keycloak.local exists and what breaks
# without it (host.docker.internal only resolving inside containers).

from flask_appbuilder.security.manager import AUTH_OAUTH

AUTH_TYPE = AUTH_OAUTH

OAUTH_PROVIDERS = [
    {
        "name": "keycloak",
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": "superset",
            "client_secret": os.environ.get("KEYCLOAK_SUPERSET_SECRET", ""),
            "client_kwargs": {"scope": "openid email profile"},
            "api_base_url": "http://keycloak.local:8180/realms/nhdw/protocol/openid-connect",
            "access_token_url": "http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/token",
            "authorize_url": "http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/auth",
            "jwks_uri": "http://keycloak.local:8180/realms/nhdw/protocol/openid-connect/certs",
        },
    }
]

# new users who log in via Keycloak get created automatically in Superset
# as this role -- "Gamma" is FAB's built-in read/query role, not admin.
# raise/lower this once real users beyond the demo login exist.
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Gamma"

# a bare AUTH_OAUTH config doesn't know how to read Keycloak's specific
# userinfo response shape -- this is the one piece FAB's default OAuth flow
# needs told explicitly for a generic OIDC provider like Keycloak (vs. a
# provider FAB ships a preset for, like Google or GitHub)
from superset.security import SupersetSecurityManager


class KeycloakSecurityManager(SupersetSecurityManager):
    def oauth_user_info(self, provider, response=None):
        if provider == "keycloak":
            me = self.appbuilder.sm.oauth_remotes[provider].get(
                "userinfo"
            ).json()
            return {
                "username": me.get("preferred_username"),
                "email": me.get("email"),
                "first_name": me.get("given_name", ""),
                "last_name": me.get("family_name", ""),
            }
        return {}


CUSTOM_SECURITY_MANAGER = KeycloakSecurityManager

# --- secret key ----------------------------------------------------------
# Superset refuses to start in a container without one set; generate a
# real one and export it as SUPERSET_SECRET_KEY before starting the
# container (see SUPERSET_SETUP.md) rather than hardcoding it here
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "")
