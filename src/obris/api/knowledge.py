import mimetypes
from pathlib import Path

from obris import routes
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


def knowledge_bulk_add(root_topic_id, items):
    """Bulk-create inline-text items under ``root_topic_id``.

    ``items`` is a list of dicts. Each must include ``topic_id`` and
    ``content``; optional fields are ``title``, ``file_name``,
    ``source_type``, ``url``, ``external_id``. Items whose UTF-8 size
    exceeds the server's ``MAX_INLINE_TEXT_SIZE`` are rejected per-row;
    callers fall back to the per-item create path for those.

    Returns ``{"created": [...], "errors": [{"index", ...}]}``. The
    HTTP call as a whole succeeds even when some rows fail — partial
    failure is the per-row ``errors`` list, not a non-2xx status.
    """
    return post(
        routes.topic_knowledge_bulk_add(root_topic_id),
        json={"items": items},
        action="Bulk-add knowledge",
    )


def knowledge_update(topic_id, item_id, *, title=None, content=None, if_match=None):
    payload = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    return patch(
        routes.topic_knowledge_item(topic_id, item_id),
        json=payload,
        headers=_if_match_header(if_match),
        action="Update knowledge",
    )


def knowledge_replace_file(item_id, filepath, *, if_match=None):
    filename = Path(filepath).name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(filepath, "rb") as f:
        return post_form(
            routes.knowledge_replace_file(item_id),
            files={"file": (filename, f, mime_type)},
            headers=_if_match_header(if_match),
            action="Replace file",
        )


def _if_match_header(if_match):
    """Build ``{"If-Match": "<rev>"}`` when the caller passed a positive
    revision; otherwise return ``None`` so the client opts out of OCC.

    Sending ``If-Match: 0`` would always 412 (no item starts at revision
    0), so a freshly-tracked entry without a known revision must skip
    the header entirely.
    """
    if not if_match or int(if_match) <= 0:
        return None
    return {"If-Match": str(int(if_match))}
