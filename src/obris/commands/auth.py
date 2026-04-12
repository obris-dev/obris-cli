import contextlib
import time
import webbrowser

import click
import requests

from obris import config, routes
from obris.api.client import ApiError
from obris.api.topics import list_topics
from obris.output import as_json, is_json

POLL_INTERVAL = 2
# Server session lives 15 minutes; a session completed near the edge stays
# readable for another COMPLETED_TTL (60s). Give the CLI a buffer past the
# session TTL so we don't time out in the same second the user authorizes.
POLL_TIMEOUT = 960
POLL_MAX_BACKOFF = 30


@click.group("auth")
def auth():
    """Manage authentication."""


@auth.command("login")
def auth_login():
    """Authenticate via browser (recommended).

    Opens a browser to log in. Works from any environment —
    copy the link if the browser doesn't open automatically.
    """
    api_base = config.get_api_base()
    app_base = config.get_app_base()

    try:
        resp = requests.post(f"{api_base}/{routes.device_sessions()}", timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        session_id = payload["session_id"]
    except requests.RequestException as e:
        raise SystemExit(f"Failed to start login session: {e}") from e
    except (ValueError, KeyError) as e:
        raise SystemExit(f"Unexpected response from login session endpoint: {e}") from e
    url = f"{app_base}/auth/device/{session_id}"

    if not is_json():
        click.echo("\nTo authenticate, open this URL in your browser:\n")
        click.echo(f"  {url}\n")

    with contextlib.suppress(webbrowser.Error):
        webbrowser.open(url)

    if not is_json():
        click.echo("Waiting for authentication...")

    try:
        session = _poll_for_completion(api_base, session_id)
    except KeyboardInterrupt:
        click.echo("\nLogin cancelled.", err=True)
        raise SystemExit(130) from None

    email = session.get("email")
    config.save_tokens(
        access_token=session["access_token"],
        refresh_token=session["refresh_token"],
        expires_in=session.get("expires_in", 3600),
        client_id=session.get("client_id", ""),
    )

    scratch_id = _detect_scratch()

    if is_json():
        as_json(
            {
                "env": config.get_active_env(),
                "email": email,
                "scratch_topic_id": scratch_id,
            }
        )
        return

    if email:
        click.echo(f"Logged in as {email}")
    env = config.get_active_env()
    if scratch_id:
        click.echo(f"[{env}] Scratch topic: {scratch_id}")
    else:
        click.echo(f"[{env}] No 'Scratch' topic found.")


@auth.command("status")
def auth_status():
    """Show current authentication status."""
    env = config.get_active_env()
    data = config._env_data()
    token = data.get(config.KEY_ACCESS_TOKEN)

    if not token:
        if is_json():
            as_json({"env": env, "authenticated": False})
            return
        click.echo(f"[{env}] Not authenticated.")
        return

    expires_at = data.get(config.KEY_TOKEN_EXPIRES_AT, "")
    scratch = data.get(config.KEY_SCRATCH_TOPIC)

    if is_json():
        as_json(
            {
                "env": env,
                "authenticated": True,
                "token_expires_at": expires_at,
                "scratch_topic_id": scratch,
            }
        )
        return

    click.echo(f"[{env}] Authenticated (OAuth token)")
    if expires_at:
        click.echo(f"[{env}] Token expires: {expires_at}")
    if scratch:
        click.echo(f"[{env}] Scratch topic: {scratch}")


@auth.command("logout")
def auth_logout():
    """Remove stored credentials."""
    env = config.get_active_env()
    data = config._env_data()

    if not data.get(config.KEY_ACCESS_TOKEN):
        if is_json():
            as_json({"env": env, "logged_out": False})
            return
        click.echo(f"[{env}] Not authenticated.")
        return

    config.clear_tokens()
    if is_json():
        as_json({"env": env, "logged_out": True})
        return
    click.echo(f"[{env}] Logged out.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _poll_for_completion(api_base, session_id):
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

        # Still pending — reset backoff and wait normally
        last_server_error = None
        backoff = POLL_INTERVAL
        _sleep_within(POLL_INTERVAL, deadline)

    if last_server_error:
        raise SystemExit(f"Login polling failed after retries: {last_server_error}")
    raise SystemExit("Login timed out. Run 'obris auth login' to try again.")


def _sleep_within(seconds, deadline):
    """Sleep for up to `seconds`, clamped so we never sleep past the deadline."""
    remaining = deadline - time.time()
    if remaining <= 0:
        return
    time.sleep(min(seconds, remaining))


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
