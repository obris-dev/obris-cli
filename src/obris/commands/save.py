from pathlib import Path

import click

from obris import config
from obris.output import as_json, is_json
from obris.utils import capture, notify, upload


@click.command()
@click.argument("filepath", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--screenshot", is_flag=True, help="Take a screenshot and upload")
@click.option("--name", default=None, help="Display name")
@click.option("--prompt", "prompt_name", is_flag=True, help="Prompt for a name via dialog")
@click.option("--topic", default=None, help="Topic ID (defaults to Scratch)")
def save(filepath, screenshot, name, prompt_name, topic):
    """Save a file or screenshot to a topic. Screenshots require macOS or Linux."""
    topic_id = topic or config.get_scratch_topic_id()

    if screenshot:
        try:
            path = capture.take_screenshot()
        except SystemExit:
            notify.send("Obris", "Screenshot cancelled")
            raise
        if prompt_name:
            name = capture.prompt_name()
            if not name:
                raise SystemExit("Name is required.")
        name = name or path.stem
        notify.send_quiet("Obris", "Uploading...")
        try:
            result = upload.upload_file(topic_id, path, name)
        except SystemExit:
            notify.send("Obris", "Upload failed")
            raise
        notify.send(
            "Obris",
            f"Uploaded '{result.get('title', name)}'",
            url=notify.topic_url(topic_id),
        )
        path.unlink(missing_ok=True)
    elif filepath:
        name = name or filepath.name
        result = upload.upload_file(topic_id, filepath, name)
    else:
        raise click.UsageError("Provide a file path or use --screenshot")

    if is_json():
        return as_json(result)
    click.echo(f"Uploaded '{result.get('title', name)}'")
    click.echo(f"  ID: {result['id']}")
