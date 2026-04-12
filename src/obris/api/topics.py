from obris import routes
from obris.api.client import get, post


def list_topics(*, name=None, is_system=None):
    params = {}
    if name is not None:
        params["name"] = name
    if is_system is not None:
        params["is_system"] = str(is_system).lower()
    return get(routes.topics(), params=params, action="List topics", unwrap=True)


def get_topic(topic_id):
    return get(routes.topic(topic_id), action="Get topic")


def create_topic(name):
    return post(routes.topics(), json={"name": name}, action="Create topic")


def list_all_topics(**kwargs):
    """Fetch all topics, handling pagination."""
    items = []
    page = 1
    while True:
        data = get(
            routes.topics(),
            params={**kwargs, "page": page, "page_size": 100},
            action="List topics",
        )
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            if not data.get("next"):
                break
        else:
            items.extend(data if isinstance(data, list) else [])
            break
        page += 1
    return items


def list_knowledge(topic_id):
    return get(routes.topic_knowledge(topic_id), action="List knowledge", unwrap=True)


def list_all_knowledge(topic_id):
    """Fetch all knowledge items for a topic, handling pagination."""
    return list(iter_knowledge(topic_id))


def iter_knowledge(topic_id):
    """Yield knowledge items for a topic, page by page."""
    page = 1
    while True:
        data = get(
            routes.topic_knowledge(topic_id),
            params={"page": page, "page_size": 100},
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
