from pathlib import Path

import click

from obris import __version__, capture, config, notify, topics, uploader


@click.group()
@click.version_option(__version__, prog_name="obris")
@click.option("--env", default=None, type=click.Choice(list(config.ENVIRONMENTS)), help="Environment override (default: prod)")
def cli(env):
    """Obris CLI — capture and upload to your personal context layer."""
    if env:
        config.set_active_env(env)


@cli.command()
@click.option("--key", required=True, help="Your Obris API key")
def auth(key):
    """Save API key and detect scratch topic."""
    env = config.get_active_env()
    cfg = config.load()
    cfg.setdefault(env, {})
    cfg[env]["api_key"] = key
    config.save(cfg)

    # Find the Scratch topic
    try:
        results = topics.list_topics(name="Scratch", is_system=True)
    except SystemExit:
        click.echo(f"[{env}] API key saved, but failed to fetch topics.")
        return

    if len(results) > 1:
        raise SystemExit(f"[{env}] Multiple Scratch system topics found — this shouldn't happen. Contact dev@obris.ai.")
    elif results:
        cfg[env]["scratch_topic_id"] = results[0]["id"]
        config.save(cfg)
        click.echo(f"[{env}] Authenticated. Scratch topic: {results[0]['id']}")
    else:
        click.echo(f"[{env}] Authenticated. No 'Scratch' topic found — create one in the app.")


@cli.command("env")
@click.argument("name", required=False, type=click.Choice(list(config.ENVIRONMENTS)))
def env_cmd(name):
    """Show or set the default environment."""
    if name:
        cfg = config.load()
        cfg["default_env"] = name
        config.save(cfg)
        click.echo(f"Default environment set to: {name}")
    else:
        click.echo(config.get_active_env())


@cli.command("capture")
@click.option("--name", "cap_name", default=None, help="Display name for the capture")
@click.option("--prompt", "prompt_name", is_flag=True, help="Prompt for a name via dialog")
@click.option("--topic", default=None, help="Topic ID (defaults to Scratch)")
def capture_cmd(cap_name, prompt_name, topic):
    """Take a screenshot and upload it."""
    topic_id = topic or config.get_scratch_topic_id()

    try:
        path = capture.take_screenshot()
    except SystemExit:
        notify.send("Obris", "Screenshot cancelled")
        raise

    if cap_name:
        name = cap_name
    elif prompt_name:
        name = capture.prompt_name()
        if not name:
            raise SystemExit("Name is required.")
    else:
        name = path.stem
    notify.send_quiet("Obris", "Uploading...")

    try:
        result = uploader.upload_file(topic_id, path, name)
    except SystemExit as e:
        notify.send("Obris", f"Upload failed")
        raise

    notify.send("Obris", f"Uploaded '{result.get('title', name)}'", url=notify.topic_url(topic_id))
    click.echo(f"Uploaded '{result.get('title', name)}'")
    click.echo(f"  ID: {result['id']}")

    path.unlink(missing_ok=True)


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, path_type=Path))
@click.option("--topic", default=None, help="Topic ID (defaults to Scratch)")
@click.option("--name", default=None, help="Display name (defaults to filename)")
def upload(filepath, topic, name):
    """Upload a file to a topic."""
    topic_id = topic or config.get_scratch_topic_id()
    name = name or filepath.name
    result = uploader.upload_file(topic_id, filepath, name)
    click.echo(f"Uploaded '{result.get('title', name)}'")
    click.echo(f"  ID: {result['id']}")


@cli.group("topic")
def topic_group():
    """Manage topics."""


@topic_group.command("list")
@click.argument("topic_id", required=False)
def topic_list(topic_id):
    """List all topics, or knowledge items in a specific topic."""
    if topic_id:
        items = topics.list_knowledge(topic_id)
        if not items:
            click.echo("No items found.")
            return
        click.echo(f"{'ID':<28}{'TITLE':<38}CREATED")
        for item in items:
            created = item.get("created_at", "")[:16].replace("T", " ")
            click.echo(f"{item['id']:<28}{item.get('title', ''):<38}{created}")
    else:
        all_topics = topics.list_topics()
        if not all_topics:
            click.echo("No topics found.")
            return
        click.echo(f"{'ID':<28}{'NAME':<22}ITEMS")
        for t in all_topics:
            click.echo(f"{t['id']:<28}{t['name']:<22}{t.get('item_count', 0)}")


@cli.group("knowledge")
def knowledge_group():
    """Manage knowledge items."""


@knowledge_group.command("move")
@click.argument("knowledge_id")
@click.option("--topic", required=True, help="Destination topic ID")
def knowledge_move(knowledge_id, topic):
    """Move a knowledge item to another topic."""
    result = topics.move_knowledge(knowledge_id, topic)
    click.echo(f"Moved to {result.get('topic_name', topic)}")


@knowledge_group.command("delete")
@click.argument("knowledge_id")
def knowledge_delete(knowledge_id):
    """Delete a knowledge item."""
    topics.delete_knowledge(knowledge_id)
    click.echo(f"Deleted {knowledge_id}")
