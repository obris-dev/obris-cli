"""Remote I/O operations for sync: pull, push, download."""

import hashlib
from pathlib import Path

import requests

from obris.api.knowledge import knowledge_replace_file, knowledge_update

from .mapping import hash_bytes, read_if_text
from .models import RemoteItem

DOWNLOAD_CHUNK_SIZE = 64 * 1024


def pull_item(item: RemoteItem, dest):
    """Write a remote item to a local file. Returns the SHA-256 hash."""
    if item.content:
        data = item.content.encode("utf-8")
        Path(dest).write_bytes(data)
        return hash_bytes(data)

    if item.file_url:
        return download_file(item.file_url, dest)

    raise ValueError(f"Item {item.id} has no content or file to pull")


def push_file(topic_id, knowledge_id, filepath, item: RemoteItem):
    """Push a local file to Obris. Returns the API response."""
    if item.is_file_source:
        return knowledge_replace_file(knowledge_id, filepath)

    content, is_text = read_if_text(filepath)
    if is_text:
        return knowledge_update(topic_id, knowledge_id, content=content)

    return knowledge_replace_file(knowledge_id, filepath)


def download_file(url, dest):
    """Stream a file from a URL to disk. Returns the SHA-256 hash."""
    h = hashlib.sha256()
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(DOWNLOAD_CHUNK_SIZE):
            f.write(chunk)
            h.update(chunk)
    return h.hexdigest()
