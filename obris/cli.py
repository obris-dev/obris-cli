from pathlib import Path

import click

from obris import capture, config, topics, uploader


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

    scratch = next((t for t in all_topics if t.get("name") == "Scratch"), None)
    if scratch:
        cfg["scratch_topic_id"] = scratch["id"]
        config.save(cfg)
        click.echo(f"Authenticated. Scratch topic: {scratch['id']}")
    else:
        click.echo("Authenticated. No 'Scratch' topic found — create one in the app.")


@cli.command("capture")
@click.option("--name", "cap_name", default=None, help="Display name for the capture")
@click.option("--auto-name", "auto", is_flag=True, help="Auto-generate a timestamped name")
@click.option("--topic", default=None, help="Topic ID (defaults to Scratch)")
def capture_cmd(cap_name, auto, topic):
    """Take a screenshot and upload it."""
    topic_id = topic or config.get_scratch_topic_id()

    path = capture.take_screenshot()

    if cap_name:
        name = cap_name
    elif auto:
        name = capture.auto_name()
    else:
        name = capture.prompt_name()

    if not name:
        raise SystemExit("Name is required.")

    result = uploader.upload_file(topic_id, path, name)
    click.echo(f"Uploaded '{result.get('title', name)}'")
    click.echo(f"  ID: {result['id']}")

    path.unlink(missing_ok=True)


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, path_type=Path))
@click.option("--topic", required=True, help="Topic ID")
@click.option("--name", default=None, help="Display name (defaults to filename)")
def upload(filepath, topic, name):
    """Upload a file to a topic."""
    name = name or filepath.name
    result = uploader.upload_file(topic, filepath, name)
    click.echo(f"Uploaded '{result.get('title', name)}'")
    click.echo(f"  ID: {result['id']}")


@cli.group("topics")
def topics_group():
    """Manage topics."""


@topics_group.command("list")
def topics_list():
    """List all topics."""
    all_topics = topics.list_topics()
    if not all_topics:
        click.echo("No topics found.")
        return

    click.echo(f"{'ID':<28}{'NAME':<22}ITEMS")
    for t in all_topics:
        click.echo(f"{t['id']:<28}{t['name']:<22}{t.get('item_count', 0)}")


@cli.group("scratch")
def scratch_group():
    """Manage scratch items."""


@scratch_group.command("list")
def scratch_list():
    """List items in the Scratch topic."""
    topic_id = config.get_scratch_topic_id()
    items = topics.list_knowledge(topic_id)
    if not items:
        click.echo("No items in Scratch.")
        return

    click.echo(f"{'ID':<28}{'TITLE':<38}CREATED")
    for item in items:
        created = item.get("created_at", "")[:16].replace("T", " ")
        click.echo(f"{item['id']:<28}{item.get('title', ''):<38}{created}")


@cli.command()
@click.argument("knowledge_id")
@click.option("--topic", required=True, help="Destination topic ID")
def move(knowledge_id, topic):
    """Move a knowledge item to another topic."""
    result = topics.move_knowledge(knowledge_id, topic)
    click.echo(f"Moved to {result.get('topic_name', topic)}")
