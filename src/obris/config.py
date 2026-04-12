import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc

import requests

from obris import routes

CONFIG_DIR = Path.home() / ".obris"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_CLOUD = "cloud"
ENV_LOCAL = "local"

KEY_API_BASE = "api_base"
KEY_APP_BASE = "app_base"
KEY_ACCESS_TOKEN = "access_token"
KEY_REFRESH_TOKEN = "refresh_token"
KEY_TOKEN_EXPIRES_AT = "token_expires_at"
KEY_CLIENT_ID = "client_id"
KEY_DEFAULT_ENV = "default_env"
KEY_ENVIRONMENTS = "environments"
KEY_SCRATCH_TOPIC = "scratch_topic_id"

REFRESH_BUFFER = timedelta(minutes=5)

BUILTIN_ENVIRONMENTS = {
    ENV_CLOUD: {
        KEY_API_BASE: "https://api.obris.ai",
        KEY_APP_BASE: "https://app.obris.ai",
    },
    ENV_LOCAL: {
        KEY_API_BASE: "http://localhost:8000",
        KEY_APP_BASE: "http://localhost:3001",
    },
}

DEFAULT_ENV = ENV_CLOUD


def get_environments():
    """Built-in environments + any custom ones from config."""
    cfg = load()
    envs = dict(BUILTIN_ENVIRONMENTS)
    for name, data in cfg.get(KEY_ENVIRONMENTS, {}).items():
        envs[name] = data
    return envs


def add_environment(name, api_base, app_base=None):
    """Add or update a custom environment."""
    cfg = load()
    cfg.setdefault(KEY_ENVIRONMENTS, {})
    cfg[KEY_ENVIRONMENTS][name] = {
        KEY_API_BASE: api_base.rstrip("/"),
        KEY_APP_BASE: (app_base or api_base).rstrip("/"),
    }
    save(cfg)


def remove_environment(name):
    """Remove a custom environment."""
    if name in BUILTIN_ENVIRONMENTS:
        raise SystemExit(f"Cannot remove built-in environment '{name}'.")
    cfg = load()
    envs = cfg.get(KEY_ENVIRONMENTS, {})
    if name not in envs:
        raise SystemExit(f"Environment '{name}' not found.")
    del envs[name]
    if cfg.get(KEY_DEFAULT_ENV) == name:
        cfg[KEY_DEFAULT_ENV] = DEFAULT_ENV
    save(cfg)


_active_env = None


def set_active_env(env):
    global _active_env
    _active_env = env


def get_active_env():
    if _active_env:
        return _active_env
    return load().get(KEY_DEFAULT_ENV, DEFAULT_ENV)


def load():
    if not CONFIG_FILE.exists():
        return {KEY_DEFAULT_ENV: DEFAULT_ENV}
    return json.loads(CONFIG_FILE.read_text())


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    data = json.dumps(cfg, indent=2) + "\n"
    fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    CONFIG_FILE.chmod(0o600)


def _env_data():
    return load().get(get_active_env(), {})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def auth_headers():
    """Return auth headers, refreshing the token if needed."""
    _refresh_if_needed()
    token = _env_data().get(KEY_ACCESS_TOKEN)
    env = get_active_env()
    if not token:
        raise SystemExit(f"Not authenticated for '{env}'. Run: obris --env {env} auth login")
    return {"Authorization": f"Bearer {token}"}


def save_tokens(access_token, refresh_token, expires_in, client_id):
    """Store OAuth tokens in config for the active environment."""
    env = get_active_env()
    cfg = load()
    cfg.setdefault(env, {})
    cfg[env][KEY_ACCESS_TOKEN] = access_token
    cfg[env][KEY_REFRESH_TOKEN] = refresh_token
    cfg[env][KEY_TOKEN_EXPIRES_AT] = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
    cfg[env][KEY_CLIENT_ID] = client_id
    save(cfg)


def clear_tokens():
    """Remove auth tokens from config for the active environment."""
    env = get_active_env()
    cfg = load()
    env_data = cfg.get(env, {})
    for key in (KEY_ACCESS_TOKEN, KEY_REFRESH_TOKEN, KEY_TOKEN_EXPIRES_AT, KEY_CLIENT_ID, KEY_SCRATCH_TOPIC):
        env_data.pop(key, None)
    save(cfg)


def _refresh_if_needed():
    """Refresh the access token if it expires within the buffer window.

    Malformed timestamps are treated as "force refresh" rather than
    crashing. Network errors on refresh raise SystemExit so the user
    knows the request can't proceed (vs. silently using an expired token).
    """
    data = _env_data()
    expires_at = data.get(KEY_TOKEN_EXPIRES_AT)
    if not expires_at:
        return

    try:
        expires = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        # Malformed — force a refresh attempt
        expires = datetime.now(UTC)

    if expires - datetime.now(UTC) > REFRESH_BUFFER:
        return

    refresh_token = data.get(KEY_REFRESH_TOKEN)
    client_id = data.get(KEY_CLIENT_ID)
    if not refresh_token or not client_id:
        raise SystemExit("Access token expired and no refresh token available. Run: obris auth login")

    try:
        resp = requests.post(
            f"{get_api_base()}/{routes.oauth_token()}",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise SystemExit(f"Failed to refresh session: {e}") from e

    if not resp.ok:
        # 4xx means the refresh token is no longer valid (revoked, expired,
        # or rotated out from under us). Clear stored credentials so
        # `auth status` stops claiming we're authenticated.
        if 400 <= resp.status_code < 500:
            clear_tokens()
        raise SystemExit("Session expired. Run: obris auth login")

    try:
        tokens = resp.json()
        access_token = tokens["access_token"]
    except (ValueError, KeyError) as e:
        raise SystemExit(f"Unexpected refresh response: {e}") from e

    save_tokens(
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", refresh_token),
        expires_in=tokens.get("expires_in", 3600),
        client_id=client_id,
    )


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def get_api_base():
    env = get_active_env()
    envs = get_environments()
    return envs.get(env, envs[DEFAULT_ENV])[KEY_API_BASE]


def get_app_base():
    env = get_active_env()
    envs = get_environments()
    return envs.get(env, envs[DEFAULT_ENV])[KEY_APP_BASE]


def get_scratch_topic_id():
    tid = _env_data().get(KEY_SCRATCH_TOPIC)
    env = get_active_env()
    if not tid:
        raise SystemExit(f"No scratch topic configured for '{env}'. Run: obris --env {env} auth login")
    return tid
