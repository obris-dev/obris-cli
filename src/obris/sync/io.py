"""Remote I/O operations for sync: pull, push, download."""

import hashlib
from pathlib import Path

import requests

from obris.api.knowledge import knowledge_detail, knowledge_replace_file, knowledge_update

from .mapping import hash_bytes, read_if_text
from .models import RemoteItem

DOWNLOAD_CHUNK_SIZE = 64 * 1024


def pull_item(item: RemoteItem, dest):
    """Write a remote item to a local file. Returns the SHA-256 hash.

    When ``item`` was synthesized from a sync-state manifest entry it
    has no inline content or file_url — the manifest omits both to
    keep the response small. In that case we fetch the full detail
    once and continue with the materialized payload. Items already
    carrying content/file_url skip the fetch.
    """
    if item.content:
        data = item.content.encode("utf-8")
        Path(dest).write_bytes(data)
        return hash_bytes(data)

    if item.file_url:
        return download_file(item.file_url, dest)

    full = RemoteItem.from_api(knowledge_detail(item.id))
    if full.content:
        data = full.content.encode("utf-8")
        Path(dest).write_bytes(data)
        return hash_bytes(data)
    if full.file_url:
        return download_file(full.file_url, dest)

    raise ValueError(f"Item {item.id} has no content or file to pull")


def push_file(topic_id, knowledge_id, filepath, item: RemoteItem, *, if_match=None):
    """Push a local file to Obris. Returns the API response.

    ``if_match`` is the revision the caller believes the server is at;
    when set, the server enforces it and rejects with 412 (raised as
    ``ConcurrentWriteError``) if a concurrent writer has bumped past
    it. Pass ``None`` to fall back to last-write-wins — used by force
    paths like conflicts resolve --keep-local.
    """
    if item.is_file_source:
        return knowledge_replace_file(knowledge_id, filepath, if_match=if_match)

    content, is_text = read_if_text(filepath)
    if is_text:
        return knowledge_update(topic_id, knowledge_id, content=content, if_match=if_match)

    return knowledge_replace_file(knowledge_id, filepath, if_match=if_match)


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
