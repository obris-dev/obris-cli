from obris import routes
from obris.api.client import get, get_etagged, post
from obris.sync.models import RemoteTopic


def list_topics(*, name=None, is_system=None, parent_id=None, roots_only=False):
    """List topics, walking all pages so callers get the full set.

    The server paginates at ``page_size=10`` by default; returning a
    single page quietly hid older topics (anything not on page 1). We
    request ``page_size=100`` per page and iterate ``next`` until it
    runs out.
    """
    base_params = {}
    if name is not None:
        base_params["name"] = name
    if is_system is not None:
        base_params["is_system"] = str(is_system).lower()
    if parent_id is not None:
        base_params["parent_id"] = parent_id
    if roots_only:
        base_params["roots_only"] = "true"

    items = []
    page = 1
    while True:
        body = get(
            routes.topics(),
            params={**base_params, "page": page, "page_size": 100},
            action="List topics",
        )
        if isinstance(body, dict) and "results" in body:
            items.extend(body["results"])
            if not body.get("next"):
                break
        else:
            items.extend(body if isinstance(body, list) else [])
            break
        page += 1
    return items


def get_topic(topic_id) -> RemoteTopic:
    """Fetch a single topic. Returns a ``RemoteTopic`` DTO so callers
    do attribute access instead of dict .get() calls — same pattern as
    ``RemoteItem`` on the knowledge side."""
    return RemoteTopic.from_api(get(routes.topic(topic_id), action="Get topic"))


def create_topic(name, *, parent_id: str | None = None) -> RemoteTopic:
    payload: dict = {"name": name}
    if parent_id:
        payload["parent_id"] = parent_id
    return RemoteTopic.from_api(post(routes.topics(), json=payload, action="Create topic"))


def fetch_subtree(topic_id) -> list[RemoteTopic]:
    """Return ``RemoteTopic`` entries for the topic and all descendants."""
    raw = get(routes.topic_subtree(topic_id), action="Fetch topic subtree", unwrap=True)
    return [RemoteTopic.from_api(r) for r in raw]


def fetch_sync_state(topic_id, *, if_none_match=None):
    """Return the sync-state manifest for a root topic, or None on 304.

    Manifest shape (when not 304)::

        {
          "root_hash": "<sha256>",
          "topics": {"<tid>": {"parent_id", "name", "subtree_hash"}},
          "items":  {"<kid>": {"content_hash", "revision", "topic_id",
                                "filename", "source_type"}}
        }

    A returned ``None`` means the server's root_hash matches
    ``if_none_match`` — the subtree is unchanged remotely and the caller
    should reuse its cached view.
    """
    return get_etagged(
        routes.topic_sync_state(topic_id),
        if_none_match=if_none_match,
        action="Fetch sync state",
    )


def list_knowledge(topic_id):
    return get(routes.topic_knowledge(topic_id), action="List knowledge", unwrap=True)


def list_all_knowledge(topic_id):
    """Fetch all knowledge items for a topic, handling pagination."""
    return list(iter_knowledge(topic_id))


def iter_knowledge(topic_id, *, recursive=False):
    """Yield knowledge items for a topic, page by page.

    When ``recursive`` is True, the server returns items from the topic
    and all its descendants. Items carry ``topic_id`` so callers can
    place them under the right subtopic.
    """
    page = 1
    base_params = {"page_size": 100}
    if recursive:
        base_params["recursive"] = "true"
    while True:
        data = get(
            routes.topic_knowledge(topic_id),
            params={**base_params, "page": page},
            action="List knowledge",
        )
        if isinstance(data, dict) and "results" in data:
            yield from data["results"]
            if not data.get("next"):
                break
        else:
            items = data if isinstance(data, list) else []
            yield from items
            break
        page += 1
