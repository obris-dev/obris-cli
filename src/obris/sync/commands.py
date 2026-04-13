"""File-level sync operations: add and link."""

from pathlib import Path

from obris.api.knowledge import knowledge_add
from obris.utils.upload import upload_file

from .mapping import hash_file, now_iso, read_if_text
from .state import SyncState


def add_file(root_topic_id, sync_dir, filepath, *, target_topic_id=None):
    """Add a local file to a topic (root or subtopic) and start tracking it.

    ``root_topic_id`` is the root of the sync tree (state key). ``target_topic_id``
    is the topic the item is actually created under — defaults to the root.

    Returns the created knowledge item dict.
    """
    sync_dir = Path(sync_dir)
    filepath = Path(filepath)
    target_topic_id = target_topic_id or root_topic_id

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    state = SyncState.load(root_topic_id, sync_dir) or SyncState(root_topic_id, sync_dir)

    filename = filepath.name
    existing_kid, _ = state.find_by_filename(filename)
    if existing_kid:
        raise SystemExit(f'"{filename}" is already tracked (item {existing_kid}). Use sync to update it.')

    file_hash = hash_file(filepath)

    content, is_text = read_if_text(filepath)
    if is_text:
        result = knowledge_add(target_topic_id, filename, content)
    else:
        result = upload_file(target_topic_id, filepath, filename)

    synced_at = result.get("updated_at") or result.get("created_at") or now_iso()
    state.track(result["id"], filename, file_hash, synced_at, topic_id=target_topic_id)
    state.save()

    return result


def link_file(root_topic_id, sync_dir, filepath, knowledge_id, *, target_topic_id=None):
    """Link a local file to an existing remote item.

    Use after renaming a local file to reattach it to its remote item.
    """
    sync_dir = Path(sync_dir)
    filepath = Path(filepath)
    target_topic_id = target_topic_id or root_topic_id

    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    state = SyncState.load(root_topic_id, sync_dir) or SyncState(root_topic_id, sync_dir)

    filename = filepath.name
    file_hash = hash_file(filepath)
    state.track(knowledge_id, filename, file_hash, now_iso(), topic_id=target_topic_id)
    state.save()
