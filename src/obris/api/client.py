"""Shared API client with auth, base URL, and error handling."""

import requests

from obris.config import auth_headers, get_api_base

TIMEOUT = 30


def _url(path):
    return f"{get_api_base()}/{path.lstrip('/')}"


def _check(resp, action="Request"):
    if not resp.ok:
        raise SystemExit(f"{action} failed ({resp.status_code}): {resp.text}")
    return resp


def _unwrap(data):
    """Handle paginated ({"results": [...]}) or plain list responses."""
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def get(path, params=None, *, action="Request"):
    resp = requests.get(_url(path), headers=auth_headers(), params=params, timeout=TIMEOUT)
    _check(resp, action)
    return _unwrap(resp.json())


def post(path, json=None, *, action="Request"):
    resp = requests.post(_url(path), headers=auth_headers(), json=json, timeout=TIMEOUT)
    _check(resp, action)
    return resp.json()


def post_form(path, files=None, data=None, *, action="Upload"):
    resp = requests.post(_url(path), headers=auth_headers(), files=files, data=data, timeout=TIMEOUT)
    _check(resp, action)
    return resp.json()


def delete(path, *, action="Delete"):
    resp = requests.delete(_url(path), headers=auth_headers(), timeout=TIMEOUT)
    _check(resp, action)
