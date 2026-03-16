from obris.api.client import delete, get, post


def knowledge_detail(knowledge_id):
    return get(f"v1/knowledge/detail/{knowledge_id}", action="Get knowledge")


def knowledge_delete(knowledge_id):
    delete(f"v1/knowledge/detail/{knowledge_id}", action="Delete knowledge")


def knowledge_move(knowledge_id, topic_id):
    return post(
        f"v1/knowledge/detail/{knowledge_id}/move",
        json={"topic_id": topic_id},
        action="Move knowledge",
    )
