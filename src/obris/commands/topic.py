import click

from obris.api.topics import fetch_subtree, list_knowledge, list_topics
from obris.output import as_json, is_json, table


@click.group("topic")
def topic_group():
    """Manage topics."""


@topic_group.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include subtopics (flat list).")
@click.option("--parent", "parent_id", metavar="TOPIC_ID", help="List direct children of a topic.")
def topic_list(show_all, parent_id):
    """List topics. Defaults to root topics only."""
    if show_all and parent_id:
        raise click.UsageError("--all and --parent are mutually exclusive.")
    if parent_id:
        topics = list_topics(parent_id=parent_id)
    elif show_all:
        topics = list_topics()
    else:
        topics = list_topics(roots_only=True)
    if is_json():
        return as_json(topics)
    if not topics:
        click.echo("No topics found.")
        return
    rows = _hierarchical_rows(topics) if show_all else [[t["id"], t["name"], t.get("item_count", 0)] for t in topics]
    table(["ID", "NAME", "ITEMS"], rows)


def _hierarchical_rows(topics):
    """Render a flat topic list as parent/subtopic rows with tree indentation.

    Subtopics whose parent is not in the list (e.g. parent belongs to another
    user) are rendered as roots so they are still visible.
    """
    by_id = {t["id"]: t for t in topics}
    children: dict[str | None, list] = {}
    for t in topics:
        pid = t.get("parent_id")
        key = pid if pid in by_id else None
        children.setdefault(key, []).append(t)
    for group in children.values():
        group.sort(key=lambda t: ((t.get("name") or "").lower(), t["id"]))

    rows: list[list] = []

    def walk(node, depth, prefix, is_last_stack):
        if depth == 0:
            label = node["name"]
        else:
            connector = "└── " if is_last_stack[-1] else "├── "
            label = f"{prefix}{connector}{node['name']}"
        rows.append([node["id"], label, node.get("item_count", 0)])
        kids = children.get(node["id"], [])
        for idx, child in enumerate(kids):
            last = idx == len(kids) - 1
            next_prefix = "" if depth == 0 else prefix + ("    " if is_last_stack[-1] else "│   ")
            walk(child, depth + 1, next_prefix, [*is_last_stack, last])

    for root in children.get(None, []):
        walk(root, 0, "", [])
    return rows


@topic_group.command("tree")
@click.argument("topic_id")
def topic_tree(topic_id):
    """Print a topic and its descendants as an ID/name/items table."""
    nodes = [_node_to_dict(n) for n in fetch_subtree(topic_id)]
    if is_json():
        return as_json(nodes)
    if not nodes:
        click.echo("No topic found.")
        return
    table(["ID", "NAME", "ITEMS"], _hierarchical_rows(nodes))


def _node_to_dict(n):
    return {
        "id": n.id,
        "name": n.name,
        "parent_id": n.parent_id,
        "item_count": n.item_count,
    }


@topic_group.command("view")
@click.argument("topic_id")
def topic_view(topic_id):
    """View a topic's subtopics and knowledge items."""
    subtopics = list_topics(parent_id=topic_id)
    items = list_knowledge(topic_id)
    if is_json():
        return as_json({"subtopics": subtopics, "items": items})
    if not subtopics and not items:
        click.echo("No subtopics or items found.")
        return
    if subtopics:
        click.echo("Subtopics")
        table(
            ["ID", "NAME", "ITEMS"],
            [[t["id"], t["name"], t.get("item_count", 0)] for t in subtopics],
        )
    if items:
        if subtopics:
            click.echo("")
        click.echo("Items")
        table(
            ["ID", "TITLE", "CREATED"],
            [[item["id"], item.get("title", ""), item.get("created_at", "")[:16].replace("T", " ")] for item in items],
        )
