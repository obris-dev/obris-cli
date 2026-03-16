import click

from obris.api.topics import list_knowledge, list_topics
from obris.output import as_json, is_json, table


@click.group("topic")
def topic_group():
    """Manage topics."""


@topic_group.command("list")
def topic_list():
    """List all topics."""
    all_topics = list_topics()
    if is_json():
        return as_json(all_topics)
    if not all_topics:
        click.echo("No topics found.")
        return
    table(
        ["ID", "NAME", "ITEMS"],
        [[t["id"], t["name"], t.get("item_count", 0)] for t in all_topics],
    )


@topic_group.command("view")
@click.argument("topic_id")
def topic_view(topic_id):
    """View a topic and its knowledge items."""
    items = list_knowledge(topic_id)
    if is_json():
        return as_json(items)
    if not items:
        click.echo("No items found.")
        return
    table(
        ["ID", "TITLE", "CREATED"],
        [[item["id"], item.get("title", ""), item.get("created_at", "")[:16].replace("T", " ")] for item in items],
    )
