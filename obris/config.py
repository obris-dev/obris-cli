import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".obris"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENVIRONMENTS = {
    "prod": {
        "api_base": "https://api.obris.ai",
        "app_base": "https://app.obris.ai",
    },
    "dev": {
        "api_base": "http://localhost:8000",
        "app_base": "http://localhost:3001",
    },
}

DEFAULT_ENV = "prod"

_active_env = None


def set_active_env(env):
    global _active_env
    _active_env = env


def get_active_env():
    if _active_env:
        return _active_env
    return load().get("default_env", DEFAULT_ENV)


def load():
    if not CONFIG_FILE.exists():
        return {"default_env": DEFAULT_ENV}
    return json.loads(CONFIG_FILE.read_text())


def save(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def _env_data():
    return load().get(get_active_env(), {})


def get_api_key():
    key = _env_data().get("api_key")
    env = get_active_env()
    if not key:
        raise SystemExit(f"Not authenticated for '{env}'. Run: obris auth --key <key> --env {env}")
    return key


def get_api_base():
    env = get_active_env()
    return ENVIRONMENTS.get(env, ENVIRONMENTS[DEFAULT_ENV])["api_base"]


def get_app_base():
    env = get_active_env()
    return ENVIRONMENTS.get(env, ENVIRONMENTS[DEFAULT_ENV])["app_base"]


def get_scratch_topic_id():
    tid = _env_data().get("scratch_topic_id")
    env = get_active_env()
    if not tid:
        raise SystemExit(f"No scratch topic configured for '{env}'. Run: obris auth --key <key> --env {env}")
    return tid
