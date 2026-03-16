import click

from obris import __version__, config, output
from obris.commands.auth import auth
from obris.commands.env import env_group
from obris.commands.knowledge import knowledge_group
from obris.commands.save import save
from obris.commands.topic import topic_group


@click.group()
@click.version_option(__version__, prog_name="obris")
@click.option("--env", default=None, help="Environment override (default: prod)")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def cli(env, json_output):
    """Obris CLI — save, organize, and access your knowledge from anywhere."""
    output.set_json_mode(json_output)
    if env:
        config.set_active_env(env)


cli.add_command(auth)
cli.add_command(save)
cli.add_command(env_group)
cli.add_command(topic_group)
cli.add_command(knowledge_group)
