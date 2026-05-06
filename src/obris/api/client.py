"""Shared API client with auth, base URL, and error handling."""

import requests

from obris.config import auth_headers, get_api_base

TIMEOUT = 30
UPLOAD_TIMEOUT = 120


class ApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ConcurrentWriteError(ApiError):
    """Raised when a write fails the server's ``If-Match`` revision check.

    The server returns 412 with a body that exposes its current revision
    and content_hash so the client can decide how to recover (mark the
    item conflicted, surface the difference to the user, etc.).
    """

    def __init__(self, message, *, current_revision, current_content_hash):
        super().__init__(message, status_code=412)
        self.current_revision = current_revision
        self.current_content_hash = current_content_hash


def _url(path):
    return f"{get_api_base()}/{path.lstrip('/')}"


def _check(resp, action="Request"):
    if resp.ok:
        return resp
    if resp.status_code == 412:
        try:
            body = resp.json() or {}
        except ValueError:
            body = {}
        raise ConcurrentWriteError(
            f"{action} failed (412 revision mismatch): {resp.text}",
            current_revision=int(body.get("current_revision") or 0),
            current_content_hash=body.get("current_content_hash") or "",
        )
    raise ApiError(f"{action} failed ({resp.status_code}): {resp.text}", status_code=resp.status_code)


def _unwrap(body):
    """Handle paginated ({"results": [...]}) or plain list responses."""
    if isinstance(body, dict) and "results" in body:
        return body["results"]
    return body


def get(path, params=None, *, action="Request", unwrap=False):
    resp = requests.get(_url(path), headers=auth_headers(), params=params, timeout=TIMEOUT)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def get_etagged(path, *, if_none_match=None, action="Request"):
    """GET that participates in ETag caching.

    Sends ``If-None-Match`` when the caller has a cached ETag and
    returns ``None`` on a 304 short-circuit. Other non-2xx statuses
    raise ``ApiError`` the same way regular ``get`` does. Used by the
    sync-state manifest endpoint, where a 304 means "subtree unchanged
    — keep using the cached state."
    """
    headers = {"If-None-Match": f'"{if_none_match}"'} if if_none_match else None
    resp = requests.get(_url(path), headers=_merge_headers(headers), timeout=TIMEOUT)
    if resp.status_code == 304:
        return None
    _check(resp, action)
    return resp.json()


def post(path, json=None, *, action="Request", unwrap=False):
    resp = requests.post(_url(path), headers=auth_headers(), json=json, timeout=TIMEOUT)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def patch(path, json=None, *, headers=None, action="Request", unwrap=False):
    resp = requests.patch(_url(path), headers=_merge_headers(headers), json=json, timeout=TIMEOUT)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def post_form(path, files=None, data=None, *, headers=None, action="Upload", unwrap=False, timeout=UPLOAD_TIMEOUT):
    resp = requests.post(_url(path), headers=_merge_headers(headers), files=files, data=data, timeout=timeout)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def _merge_headers(extra):
    base = auth_headers() or {}
    if not extra:
        return base
    merged = dict(base)
    merged.update(extra)
    return merged


def delete(path, *, action="Delete"):
    resp = requests.delete(_url(path), headers=auth_headers(), timeout=TIMEOUT)
    _check(resp, action)
