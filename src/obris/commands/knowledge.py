import click

from obris.api.knowledge import knowledge_delete, knowledge_detail, knowledge_move
from obris.output import as_json, is_json, kv


@click.group("knowledge")
def knowledge_group():
    """Manage knowledge items."""


@knowledge_group.command("view")
@click.argument("knowledge_id")
def view(knowledge_id):
    """View details of a knowledge item."""
    item = knowledge_detail(knowledge_id)
    if is_json():
        return as_json(item)
    pairs = [
        ("ID", item.get("id", "")),
        ("Title", item.get("title", "")),
        ("Type", item.get("content_type", item.get("mime_type", ""))),
        ("Topic", item.get("topic_name", item.get("topic_id", ""))),
        ("Created", item.get("created_at", "")[:16].replace("T", " ")),
    ]
    if item.get("summary"):
        pairs.append(("Summary", item["summary"][:200]))
    if item.get("file_url"):
        pairs.append(("File", item["file_url"]))
    kv(pairs)


@knowledge_group.command("move")
@click.argument("knowledge_id")
@click.option("--topic", required=True, help="Destination topic ID")
def move(knowledge_id, topic):
    """Move a knowledge item to another topic."""
    result = knowledge_move(knowledge_id, topic)
    if is_json():
        return as_json(result)
    click.echo(f"Moved to {result.get('topic_name', topic)}")


@knowledge_group.command("delete")
@click.argument("knowledge_id")
def delete(knowledge_id):
    """Delete a knowledge item."""
    knowledge_delete(knowledge_id)
    if is_json():
        return as_json({"id": knowledge_id, "deleted": True})
    click.echo(f"Deleted {knowledge_id}")
