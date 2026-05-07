<p align="center">
  <a href="https://obris.ai">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./.assets/obris-logo-light.svg">
      <source media="(prefers-color-scheme: light)" srcset="./.assets/obris-logo-dark.svg">
      <img src="./.assets/obris-logo-dark.svg" alt="Obris" width="200">
    </picture>
  </a>
</p>

<p align="center">
  Save, organize, and access your knowledge from the command line.
</p>

<p align="center">
  <a href="https://pypi.org/project/obris-cli/"><img src="https://img.shields.io/pypi/v/obris-cli.svg" alt="PyPI"></a>
  <a href="https://github.com/obris-dev/obris-cli/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License"></a>
</p>

## Install

```bash
pip install obris-cli
```

## Authenticate

```bash
obris auth login
```

Opens a browser to log in. The CLI waits, you authorize, done. Works from any machine: the login URL can be opened on any device with a browser. Connects to Obris Cloud by default. See [Selfhosted](#selfhosted) for your own instance.

## Commands

| Command | Description |
|---------|-------------|
| `obris auth login` | Authenticate via browser |
| `obris auth status` | Show current authentication |
| `obris auth logout` | Remove stored credentials |
| `obris save <file>` | Save a file to a topic |
| `obris save --screenshot` | Take a screenshot and save it |
| `obris sync [path]` | Sync a directory with an Obris topic |
| `obris sync add <file>` | Add a local file to a synced topic |
| `obris sync link <file> -i <id>` | Relink a renamed file |
| `obris sync unlink <file-or-id>` | Break the local-to-remote sync link |
| `obris topic list` | List all topics |
| `obris topic view <id>` | View a topic and its knowledge items |
| `obris knowledge view <id>` | View a knowledge item |
| `obris knowledge move <id> --topic <id>` | Move to another topic |
| `obris knowledge delete <id>` | Delete a knowledge item |
| `obris env list` | List all environments |
| `obris env view [name]` | Show environment details |
| `obris env use <name>` | Set the default environment |
| `obris env add <name> --url <url>` | Add a selfhosted instance |
| `obris env remove <name>` | Remove an environment |

## Selfhosted

Point the CLI at your own Obris instance:

```bash
obris env add myserver --url https://obris.example.com
obris --env myserver auth login
```

## JSON output

Every command supports `--json` for machine-readable output:

```bash
obris --json topic list
obris --json knowledge view <id>
obris --json auth status
```

## License

Apache 2.0. See [LICENSE](../LICENSE).
