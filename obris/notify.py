import shutil
import subprocess
import sys
from pathlib import Path

ICON_PATH = str(Path(__file__).parent / "assets" / "icon.png")

# api.obris.ai -> app.obris.ai, localhost:8000 -> localhost:3001
APP_BASE_MAP = {
    "https://api.obris.ai": "https://app.obris.ai",
    "http://localhost:8000": "http://localhost:3001",
}

_has_notifier = sys.platform == "darwin" and shutil.which("terminal-notifier") is not None


def _get_app_base():
    from obris.config import get_api_base
    api_base = get_api_base()
    return APP_BASE_MAP.get(api_base, api_base.replace("api.", "app."))


def _osascript_notify(title, message):
    title = title.replace('"', '\\"')
    message = message.replace('"', '\\"')
    subprocess.run([
        "osascript", "-e",
        f'display notification "{message}" with title "{title}"',
    ])


def send(title, message, url=None):
    if sys.platform != "darwin":
        import click
        click.echo(f"{title}: {message}")
        return

    if _has_notifier:
        cmd = [
            "terminal-notifier",
            "-title", title,
            "-message", message,
            "-contentImage", ICON_PATH,
            "-sound", "default",
        ]
        if url:
            cmd += ["-open", url]
        subprocess.run(cmd)
    else:
        _osascript_notify(title, message)


def send_quiet(title, message):
    """Notification without sound (for transient states like 'Uploading...')."""
    if sys.platform != "darwin":
        import click
        click.echo(f"{title}: {message}")
        return

    if _has_notifier:
        subprocess.run([
            "terminal-notifier",
            "-title", title,
            "-message", message,
            "-contentImage", ICON_PATH,
        ])
    else:
        _osascript_notify(title, message)


def topic_url(topic_id):
    return f"{_get_app_base()}/topics/{topic_id}"