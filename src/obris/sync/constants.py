PUSHED = "pushed"
PULLED = "pulled"
CONFLICT = "conflict"
MISSING = "missing"

STATUS_READY = "ready"

# Server-side cap on inline-text body in the bulk-add endpoint. Items
# whose UTF-8-encoded content exceeds this fall back to the per-item
# create / upload path. Mirrors ``MAX_INLINE_TEXT_SIZE`` in
# ``core/knowledge/services/knowledge_crud.py`` — keep in sync.
MAX_INLINE_TEXT_SIZE = 40 * 1024
