from obris.api.client import get


def list_topics(*, name=None, is_system=None):
    params = {}
    if name is not None:
        params["name"] = name
    if is_system is not None:
        params["is_system"] = str(is_system).lower()
    return get("v1/topics", params=params, action="List topics")


def list_knowledge(topic_id):
    return get(f"v1/topics/{topic_id}/knowledge", action="List knowledge")
