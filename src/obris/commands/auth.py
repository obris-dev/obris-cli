import contextlib
import webbrowser

import click

from obris import config
from obris.auth.session import check_session, finalize_login, poll_for_completion, start_session
from obris.output import as_json, is_json


@click.group("auth")
def auth():
    """Manage authentication."""


@auth.command("login")
@click.option(
    "--no-wait",
    is_flag=True,
    help="Print the login URL and exit without polling. Finish with `obris auth complete`.",
)
def auth_login(no_wait):
    """Authenticate via browser (recommended).

    Opens a browser to log in. Works from any environment — copy the
    link if the browser doesn't open automatically.

    By default, the CLI polls in the foreground and exits once login is
    complete. Pass `--no-wait` to print the URL and exit immediately;
    when you (or your user) have authorized in the browser, run
    `obris auth complete` to finalize. This mode is required for LLMs
    and scripted contexts, where blocking the caller would prevent the
    URL from being relayed to the user.
    """
    api_base = config.get_api_base()
    app_base = config.get_app_base()

    session_id = start_session(api_base)
    url = f"{app_base}/auth/device/{session_id}"

    if not is_json():
        click.echo("\nTo authenticate, open this URL in your browser:\n")
        click.echo(f"  {url}\n")

    with contextlib.suppress(webbrowser.Error):
        webbrowser.open(url)

    env = config.get_active_env()

    if no_wait:
        config.save_pending_session(session_id)
        if is_json():
            as_json({"env": env, "session_id": session_id, "url": url, "status": "pending"})
            return
        click.echo(f"[{env}] After authorizing, run: obris auth complete")
        return

    if not is_json():
        click.echo("Waiting for authentication...")

    try:
        session = poll_for_completion(api_base, session_id)
    except KeyboardInterrupt:
        click.echo("\nLogin cancelled.", err=True)
        raise SystemExit(130) from None

    finalize_login(session)


@auth.command("status")
def auth_status():
    """Show current authentication status (read-only).

    Reports whether an access token is stored for the active env and,
    if so, when it expires. If a login was started with `--no-wait` and
    hasn't been finalized yet, reports that the session is pending.
    This command never mutates stored state; run `obris auth complete`
    to finalize a pending session.
    """
    env = config.get_active_env()
    data = config._env_data()
    token = data.get(config.KEY_ACCESS_TOKEN)
    pending = config.get_pending_session()

    if not token:
        if is_json():
            as_json({"env": env, "authenticated": False, "pending": bool(pending)})
            return
        if pending:
            click.echo(f"[{env}] Login pending. Finish with: obris auth complete")
        else:
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


@auth.command("complete")
def auth_complete():
    """Finalize a pending `auth login --no-wait` session.

    Checks the pending session once and, if the user has authorized in
    the browser, saves the tokens and clears the pending state. Exits
    non-zero if no pending session exists or the session has expired.
    """
    env = config.get_active_env()
    pending = config.get_pending_session()

    if not pending:
        if is_json():
            as_json({"env": env, "completed": False, "reason": "no_pending_session"})
            raise SystemExit(1)
        raise SystemExit(f"[{env}] No pending login session. Start one with: obris auth login --no-wait")

    api_base = config.get_api_base()
    session = check_session(api_base, pending)

    if session is None:
        config.clear_pending_session()
        if is_json():
            as_json({"env": env, "completed": False, "reason": "session_expired"})
            raise SystemExit(1)
        raise SystemExit(f"[{env}] Pending login session expired. Run: obris auth login --no-wait")

    if session.get("status") != "completed":
        app_base = config.get_app_base()
        url = f"{app_base}/auth/device/{pending}"
        if is_json():
            as_json({"env": env, "completed": False, "reason": "still_pending", "url": url})
            raise SystemExit(1)
        raise SystemExit(f"[{env}] Login still pending. Open: {url}")

    finalize_login(session)
    config.clear_pending_session()


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
    config.clear_pending_session()
    if is_json():
        as_json({"env": env, "logged_out": True})
        return
    click.echo(f"[{env}] Logged out.")
