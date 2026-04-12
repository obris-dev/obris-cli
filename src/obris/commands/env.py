import click

from obris import config
from obris.output import as_json, is_json


@click.group("env")
def env_group():
    """Manage environments."""


@env_group.command("list")
def env_list():
    """List all environments."""
    envs = config.get_environments()
    active = config.get_active_env()
    if is_json():
        return as_json([{"name": k, "active": k == active, **v} for k, v in envs.items()])
    for name, data in envs.items():
        marker = " *" if name == active else ""
        click.echo(f"  {name}{marker}  {data['api_base']}")


@env_group.command("view")
@click.argument("name", required=False)
def env_view(name):
    """Show environment details. Defaults to the active environment."""
    env = name or config.get_active_env()
    envs = config.get_environments()
    data = envs.get(env)
    if not data:
        raise SystemExit(f"Unknown environment '{env}'. Run: obris env list")
    active = config.get_active_env()
    if is_json():
        return as_json({"name": env, "active": env == active, **data})
    click.echo(f"Environment: {env}{'  (active)' if env == active else ''}")
    click.echo(f"API:         {data.get(config.KEY_API_BASE, 'not set')}")
    click.echo(f"App:         {data.get(config.KEY_APP_BASE, 'not set')}")


@env_group.command("use")
@click.argument("name")
def env_use(name):
    """Set the default environment."""
    envs = config.get_environments()
    if name not in envs:
        raise SystemExit(f"Unknown environment '{name}'. Run: obris env list")
    cfg = config.load()
    cfg["default_env"] = name
    config.save(cfg)
    if is_json():
        return as_json({"env": name, "active": True, **envs[name]})
    click.echo(f"Default environment set to: {name}")


@env_group.command("add")
@click.argument("name")
@click.option("--url", required=True, help="Base URL (e.g. https://obris.example.com)")
def env_add(name, url):
    """Add a custom environment."""
    config.add_environment(name, api_base=url, app_base=url)

    cfg = config.load()
    if click.confirm(f"Set '{name}' as default environment?", default=True):
        cfg[config.KEY_DEFAULT_ENV] = name
        config.save(cfg)

    if is_json():
        return as_json({"env": name, config.KEY_API_BASE: url})
    click.echo(f"Added environment '{name}' -> {url}")
    click.echo(f"Run 'obris --env {name} auth login' to authenticate.")


@env_group.command("remove")
@click.argument("name")
def env_remove(name):
    """Remove a custom environment."""
    config.remove_environment(name)
    if is_json():
        return as_json({"env": name, "removed": True})
    click.echo(f"Removed environment '{name}'.")
