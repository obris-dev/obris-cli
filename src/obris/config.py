import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".obris"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_CLOUD = "cloud"
ENV_LOCAL = "local"

KEY_API_BASE = "api_base"
KEY_APP_BASE = "app_base"
KEY_API_KEY = "api_key"
KEY_DEFAULT_ENV = "default_env"
KEY_ENVIRONMENTS = "environments"
KEY_SCRATCH_TOPIC = "scratch_topic_id"

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
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def _env_data():
    return load().get(get_active_env(), {})


def get_api_key():
    key = _env_data().get(KEY_API_KEY)
    env = get_active_env()
    if not key:
        raise SystemExit(f"Not authenticated for '{env}'. Run: obris --env {env} auth --key <key>")
    return key


def auth_headers():
    return {"X-API-Key": get_api_key()}


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
        raise SystemExit(f"No scratch topic configured for '{env}'. Run: obris --env {env} auth --key <key>")
    return tid
