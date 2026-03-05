import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".obris"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "api_base": "https://api.obris.ai",
    "scratch_topic_id": "",
}


def load():
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}


def save(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")


def get_api_key():
    cfg = load()
    key = cfg.get("api_key")
    if not key:
        raise SystemExit("Not authenticated. Run: obris auth --key <key>")
    return key


def get_api_base():
    return load().get("api_base", DEFAULT_CONFIG["api_base"])


def get_scratch_topic_id():
    cfg = load()
    tid = cfg.get("scratch_topic_id")
    if not tid:
        raise SystemExit("No scratch topic configured. Run: obris auth --key <key>")
    return tid
