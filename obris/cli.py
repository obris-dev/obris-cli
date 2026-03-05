from pathlib import Path

import click

from obris import capture, config, notify, topics, uploader


@click.group()
def cli():
    """Obris CLI — capture and upload to your personal context layer."""


@cli.command()
@click.option("--key", required=True, help="Your Obris API key")
@click.option("--base", default=None, help="API base URL (e.g. http://localhost:8000)")
def auth(key, base):
    """Save API key and detect scratch topic."""
    cfg = config.load()
    cfg["api_key"] = key
    if base:
        cfg["api_base"] = base.rstrip("/")
    config.save(cfg)

    # Find the Scratch topic
    try:
        all_topics = topics.list_topics()
    except SystemExit:
        click.echo("API key saved, but failed to fetch topics.")
        return

    scratch = next((t for t in all_topics if t.get("name") == "Scratch" and t.get("is_system")), None)
    if scratch:
        cfg["scratch_topic_id"] = scratch["id"]
        config.save(cfg)
        click.echo(f"Authenticated. Scratch topic: {scratch['id']}")
    else:
        click.echo("Authenticated. No 'Scratch' topic found — create one in the app.")


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
