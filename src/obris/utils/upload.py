import mimetypes

from obris.api.client import post_form


def upload_file(topic_id, filepath, name):
    filename = filepath.name if hasattr(filepath, "name") else str(filepath)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    with open(filepath, "rb") as f:
        return post_form(
            "v1/knowledge/upload",
            files={"file": (filename, f, mime_type)},
            data={"topic_id": topic_id, "title": name},
            action="Upload",
        )
