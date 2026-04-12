"""Device auth session lifecycle: start, poll, check, finalize."""

import time

import click
import requests

from obris import config, routes
from obris.api.client import ApiError
from obris.api.topics import list_topics
from obris.output import as_json, is_json

POLL_INTERVAL = 2
# Server session lives 15 minutes (SESSION_TTL); a completed session is
# readable for another COMPLETED_TTL (300s). Clamp the CLI deadline past
# both so we don't time out in the same second the user authorizes.
POLL_TIMEOUT = 1200
POLL_MAX_BACKOFF = 30


def start_session(api_base):
    """POST a new device auth session and return its session_id."""
    try:
        resp = requests.post(f"{api_base}/{routes.device_sessions()}", timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        return payload["session_id"]
    except requests.RequestException as e:
        raise SystemExit(f"Failed to start login session: {e}") from e
    except (ValueError, KeyError) as e:
        raise SystemExit(f"Unexpected response from login session endpoint: {e}") from e


def check_session(api_base, session_id):
    """One-shot session check used by `auth complete`.

    Returns the session dict if readable, or None if the session is
    gone (404). Unlike `poll_for_completion`, this does not loop or
    retry — callers are expected to invoke it at most once per command
    run.
    """
    poll_url = f"{api_base}/{routes.device_session(session_id)}"
    try:
        resp = requests.get(poll_url, timeout=10)
    except requests.RequestException as e:
        raise SystemExit(f"Failed to check login session: {e}") from e

    if resp.status_code == 404:
        return None
    if not resp.ok:
        raise SystemExit(f"Failed to check login session ({resp.status_code}): {resp.text}")

    try:
        return resp.json()
    except ValueError as e:
        raise SystemExit(f"Unexpected response from login session endpoint: {e}") from e


def poll_for_completion(api_base, session_id):
    """Poll the session endpoint until completed or expired.

    Backs off on server errors (5xx, 429) with exponential delay,
    logging each retry. Returns the completed session data.
    """
    deadline = time.time() + POLL_TIMEOUT
    poll_url = f"{api_base}/{routes.device_session(session_id)}"
    backoff = POLL_INTERVAL
    last_server_error = None

    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break

        try:
            resp = requests.get(poll_url, timeout=10)
        except requests.RequestException as e:
            last_server_error = str(e)
            click.echo(f"  Network error polling session: {e}, retrying", err=True)
            _sleep_within(backoff, deadline)
            backoff = min(backoff * 2, POLL_MAX_BACKOFF)
            continue

        if resp.status_code == 404:
            raise SystemExit("Login session expired. Run 'obris auth login' to try again.")

        if resp.status_code >= 500 or resp.status_code == 429:
            last_server_error = f"HTTP {resp.status_code}"
            click.echo(f"  Server returned {resp.status_code}, retrying", err=True)
            _sleep_within(backoff, deadline)
            backoff = min(backoff * 2, POLL_MAX_BACKOFF)
            continue

        if not resp.ok:
            raise SystemExit(f"Login failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        if data.get("status") == "completed":
            if not data.get("access_token"):
                raise SystemExit("Session completed but no token received.")
            return data

        last_server_error = None
        backoff = POLL_INTERVAL
        _sleep_within(POLL_INTERVAL, deadline)

    if last_server_error:
        raise SystemExit(f"Login polling failed after retries: {last_server_error}")
    raise SystemExit("Login timed out. Run 'obris auth login' to try again.")


def finalize_login(session):
    """Save tokens from a completed session, detect the Scratch topic,
    and report to the user. Shared by the blocking and non-blocking
    login paths.
    """
    email = session.get("email")
    config.save_tokens(
        access_token=session["access_token"],
        refresh_token=session["refresh_token"],
        expires_in=session.get("expires_in", 3600),
        client_id=session.get("client_id", ""),
    )

    scratch_id = _detect_scratch()
    env = config.get_active_env()

    if is_json():
        as_json(
            {
                "env": env,
                "email": email,
                "scratch_topic_id": scratch_id,
            }
        )
        return

    if email:
        click.echo(f"Logged in as {email}")
    if scratch_id:
        click.echo(f"[{env}] Scratch topic: {scratch_id}")
    else:
        click.echo(f"[{env}] No 'Scratch' topic found.")


def _detect_scratch():
    """Detect and store the Scratch topic ID. Returns the ID or None."""
    env = config.get_active_env()

    try:
        results = list_topics(name="Scratch", is_system=True)
    except ApiError as e:
        click.echo(f"[{env}] Warning: could not detect Scratch topic: {e}", err=True)
        return None

    scratch_id = results[0]["id"] if results else None
    if scratch_id:
        cfg = config.load()
        cfg.setdefault(env, {})
        cfg[env][config.KEY_SCRATCH_TOPIC] = scratch_id
        config.save(cfg)
    return scratch_id


def _sleep_within(seconds, deadline):
    """Sleep for up to `seconds`, clamped so we never sleep past the deadline."""
    remaining = deadline - time.time()
    if remaining <= 0:
        return
    time.sleep(min(seconds, remaining))
