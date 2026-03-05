import requests

from obris.config import get_api_base, get_api_key


def _headers():
    return {"X-API-Key": get_api_key()}


def _unwrap(data):
    """Handle paginated ({"results": [...]}) or plain list responses."""
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def list_topics():
    resp = requests.get(f"{get_api_base()}/v1/topics", headers=_headers())
    if not resp.ok:
        raise SystemExit(f"Failed to list topics ({resp.status_code}): {resp.text}")
    return _unwrap(resp.json())


def list_knowledge(topic_id):
    resp = requests.get(
        f"{get_api_base()}/v1/topics/{topic_id}/knowledge", headers=_headers()
    )
    if not resp.ok:
        raise SystemExit(f"Failed to list knowledge ({resp.status_code}): {resp.text}")
    return _unwrap(resp.json())


def move_knowledge(knowledge_id, topic_id):
    resp = requests.post(
        f"{get_api_base()}/v1/knowledge/{knowledge_id}/move",
        headers=_headers(),
        json={"topic_id": topic_id},
    )
    if not resp.ok:
        raise SystemExit(f"Move failed ({resp.status_code}): {resp.text}")
    return resp.json()
