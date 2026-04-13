"""API route builders. Single source of truth for all endpoint paths."""


def topics():
    return "v1/topics"


def topic(topic_id):
    return f"v1/topics/{topic_id}"


def topic_subtree(topic_id):
    return f"v1/topics/{topic_id}/subtree"


def topic_knowledge(topic_id):
    return f"v1/topics/{topic_id}/knowledge"


def topic_knowledge_item(topic_id, item_id):
    return f"v1/topics/{topic_id}/knowledge/{item_id}"


def knowledge_upload():
    return "v1/knowledge/upload"


def knowledge_detail(item_id):
    return f"v1/knowledge/detail/{item_id}"


def knowledge_move(item_id):
    return f"v1/knowledge/detail/{item_id}/move"


def knowledge_replace_file(item_id):
    return f"v1/knowledge/detail/{item_id}/replace-file"


def oauth_token():
    return "oauth/token/"


def device_sessions():
    return "v1/auth/device-sessions"


def device_session(session_id):
    return f"v1/auth/device-sessions/{session_id}"
