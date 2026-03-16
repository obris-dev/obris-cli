import click

from obris import config
from obris.api.topics import list_topics
from obris.output import as_json, is_json


@click.command()
@click.option("--key", default=None, help="Your Obris API key")
def auth(key):
    """Save API key and detect scratch topic."""
    env = config.get_active_env()
    envs = config.get_environments()
    if env not in envs:
        raise SystemExit(f"Environment '{env}' not found. Create it first: obris env add {env} --url <url>")
    if not key:
        key = click.prompt("API key", hide_input=True)
    # Temporarily set the key so list_topics can use it for validation
    cfg = config.load()
    cfg.setdefault(env, {})
    old_key = cfg[env].get(config.KEY_API_KEY)
    old_scratch = cfg[env].get(config.KEY_SCRATCH_TOPIC)
    cfg[env][config.KEY_API_KEY] = key
    config.save(cfg)

    try:
        results = list_topics(name="Scratch", is_system=True)
    except SystemExit as e:
        # Restore previous key and scratch topic on failure
        if old_key:
            cfg[env][config.KEY_API_KEY] = old_key
        else:
            cfg[env].pop(config.KEY_API_KEY, None)
        if old_scratch:
            cfg[env][config.KEY_SCRATCH_TOPIC] = old_scratch
        config.save(cfg)
        click.echo(f"[{env}] Authentication failed: {e}")
        return

    if len(results) > 1:
        raise SystemExit(f"[{env}] Multiple Scratch system topics found. Contact dev@obris.ai.")

    cfg[env].pop(config.KEY_SCRATCH_TOPIC, None)
    scratch_id = results[0]["id"] if results else None
    if scratch_id:
        cfg[env][config.KEY_SCRATCH_TOPIC] = scratch_id
    config.save(cfg)

    if is_json():
        return as_json({"env": env, "scratch_topic_id": scratch_id})
    if scratch_id:
        click.echo(f"[{env}] Authenticated. Scratch topic: {scratch_id}")
    else:
        click.echo(f"[{env}] Authenticated. No 'Scratch' topic found - create one in the app.")
