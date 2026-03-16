"""Centralized output formatting for the CLI."""

import json

import click

_json_mode = False


def set_json_mode(enabled):
    global _json_mode
    _json_mode = enabled


def is_json():
    return _json_mode


def as_json(data):
    click.echo(json.dumps(data, indent=2, default=str))


def _display(val):
    if val is None:
        return "(none)"
    return str(val)


def table(headers, rows):
    """Print a simple aligned table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(_display(val)))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    click.echo(fmt.format(*headers))
    for row in rows:
        click.echo(fmt.format(*[_display(v) for v in row]))


def kv(pairs):
    """Print key-value pairs aligned."""
    if not pairs:
        return
    max_key = max(len(k) for k, _ in pairs)
    for key, val in pairs:
        click.echo(f"{key + ':':<{max_key + 2}} {val}")
