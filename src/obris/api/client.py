"""Shared API client with auth, base URL, and error handling."""

import requests

from obris.config import auth_headers, get_api_base

TIMEOUT = 30
UPLOAD_TIMEOUT = 120


class ApiError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _url(path):
    return f"{get_api_base()}/{path.lstrip('/')}"


def _check(resp, action="Request"):
    if not resp.ok:
        raise ApiError(f"{action} failed ({resp.status_code}): {resp.text}", status_code=resp.status_code)
    return resp


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


def post(path, json=None, *, action="Request", unwrap=False):
    resp = requests.post(_url(path), headers=auth_headers(), json=json, timeout=TIMEOUT)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def patch(path, json=None, *, action="Request", unwrap=False):
    resp = requests.patch(_url(path), headers=auth_headers(), json=json, timeout=TIMEOUT)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def post_form(path, files=None, data=None, *, action="Upload", unwrap=False, timeout=UPLOAD_TIMEOUT):
    resp = requests.post(_url(path), headers=auth_headers(), files=files, data=data, timeout=timeout)
    _check(resp, action)
    body = resp.json()
    return _unwrap(body) if unwrap else body


def delete(path, *, action="Delete"):
    resp = requests.delete(_url(path), headers=auth_headers(), timeout=TIMEOUT)
    _check(resp, action)
