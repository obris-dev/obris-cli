import mimetypes
from pathlib import Path

from obris import routes
from obris.api.client import post_form


def upload_file(topic_id, filepath, name):
    filename = Path(filepath).name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    with open(filepath, "rb") as f:
        return post_form(
            routes.knowledge_upload(),
            files={"file": (filename, f, mime_type)},
            data={"topic_id": topic_id, "title": name},
            action="Upload",
        )
