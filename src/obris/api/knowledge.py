import mimetypes
from pathlib import Path

from obris.api import routes
from obris.api.client import delete, get, patch, post, post_form


def knowledge_detail(knowledge_id):
    return get(routes.knowledge_detail(knowledge_id), action="Get knowledge")


def knowledge_delete(knowledge_id):
    delete(routes.knowledge_detail(knowledge_id), action="Delete knowledge")


def knowledge_move(knowledge_id, topic_id):
    return post(
        routes.knowledge_move(knowledge_id),
        json={"topic_id": topic_id},
        action="Move knowledge",
    )


def knowledge_add(topic_id, title, content, source_type="cli"):
    return post(
        routes.topic_knowledge(topic_id),
        json={"title": title, "content": content, "source_type": source_type},
        action="Create knowledge",
    )


def knowledge_update(topic_id, item_id, *, title=None, content=None):
    payload = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    return patch(
        routes.topic_knowledge_item(topic_id, item_id),
        json=payload,
        action="Update knowledge",
    )


def knowledge_replace_file(item_id, filepath):
    filename = Path(filepath).name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(filepath, "rb") as f:
        return post_form(
            routes.knowledge_replace_file(item_id),
            files={"file": (filename, f, mime_type)},
            action="Replace file",
        )
