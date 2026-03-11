import mimetypes

import requests

from obris.config import get_api_base, get_api_key


def upload_file(topic_id, filepath, name):
    url = f"{get_api_base()}/v1/knowledge/upload"
    headers = {"X-API-Key": get_api_key()}
    filename = filepath.name if hasattr(filepath, "name") else str(filepath)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    with open(filepath, "rb") as f:
        resp = requests.post(
            url,
            headers=headers,
            files={"file": (filename, f, mime_type)},
            data={"topic_id": topic_id, "title": name},
        )

    if not resp.ok:
        raise SystemExit(f"Upload failed ({resp.status_code}): {resp.text}")

    return resp.json()