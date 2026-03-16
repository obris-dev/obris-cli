import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".obris"
CONFIG_FILE = CONFIG_DIR / "config.json"

BUILTIN_ENVIRONMENTS = {
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


def get_environments():
    """Built-in environments + any custom ones from config."""
    cfg = load()
    envs = dict(BUILTIN_ENVIRONMENTS)
    for name, data in cfg.get("environments", {}).items():
        envs[name] = data
    return envs


def add_environment(name, api_base, app_base=None):
    """Add or update a custom environment."""
    cfg = load()
    cfg.setdefault("environments", {})
    cfg["environments"][name] = {
        "api_base": api_base.rstrip("/"),
        "app_base": (app_base or api_base).rstrip("/"),
    }
    save(cfg)


def remove_environment(name):
    """Remove a custom environment."""
    if name in BUILTIN_ENVIRONMENTS:
        raise SystemExit(f"Cannot remove built-in environment '{name}'.")
    cfg = load()
    envs = cfg.get("environments", {})
    if name not in envs:
        raise SystemExit(f"Environment '{name}' not found.")
    del envs[name]
    if cfg.get("default_env") == name:
        cfg["default_env"] = DEFAULT_ENV
    save(cfg)


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
        raise SystemExit(f"Not authenticated for '{env}'. Run: obris --env {env} auth --key <key>")
    return key


def get_api_base():
    env = get_active_env()
    envs = get_environments()
    return envs.get(env, envs[DEFAULT_ENV])["api_base"]


def get_app_base():
    env = get_active_env()
    envs = get_environments()
    return envs.get(env, envs[DEFAULT_ENV])["app_base"]


def get_scratch_topic_id():
    tid = _env_data().get("scratch_topic_id")
    env = get_active_env()
    if not tid:
        raise SystemExit(f"No scratch topic configured for '{env}'. Run: obris --env {env} auth --key <key>")
    return tid
