# Obris CLI

A command-line tool for capturing screenshots and managing knowledge in [Obris](https://obris.ai), your personal knowledge layer for AI. Save content to organized topics so you never start another AI chat from zero again.

## Install

Requires Python 3.10+.

```bash
pip install obris-cli
```

Or run directly with [uv](https://docs.astral.sh/uv/):

```bash
uvx obris-cli --help
```

### Optional: macOS notifications

For desktop notifications with deep linking to your uploaded content:

```bash
brew install terminal-notifier
```

## Setup

### 1. Get your API key

Generate an API key from your [Obris dashboard](https://app.obris.ai/api-keys). Don't have an account? [Sign up](https://app.obris.ai/signup).

### 2. Authenticate

```bash
obris auth --key <your-api-key>
```

This saves your key locally to `~/.obris/config.json` and detects your Scratch topic (the default destination for captures).

## Usage

### Capture a screenshot

```bash
obris capture                       # screenshot + upload to Scratch
obris capture --name "my pic"       # explicit name
obris capture --prompt              # prompt for a name via dialog
obris capture --topic <id>          # upload to a specific topic
```

### Upload a file

```bash
obris upload photo.png              # upload to Scratch
obris upload photo.png --topic <id> # upload to a specific topic
```

### Manage topics

```bash
obris topic list                    # list all topics
obris topic list <topic_id>         # list knowledge in a topic
```

### Manage knowledge

```bash
obris knowledge move <id> --topic <id>  # move to another topic
obris knowledge delete <id>             # delete a knowledge item
```

## Hotkeys

Bind keyboard shortcuts to capture commands using any automation tool — [Alfred](https://www.alfredapp.com/), [Raycast](https://www.raycast.com/), [Keyboard Maestro](https://www.keyboardmaestro.com/), macOS Shortcuts, etc.

### Example: Alfred

Create a workflow with a **Hotkey** trigger connected to a **Run Script** action (language: `/bin/zsh`):

**Quick capture:**

```zsh
/full/path/to/obris capture
```

**Capture with name prompt:**

```zsh
/full/path/to/obris capture --prompt
```

> **Tip:** Use the full path to the `obris` binary since Alfred doesn't load your shell profile. Run `which obris` to find it.

## Platform support

| Platform | Capture | Upload / Topics / Knowledge |
|----------|---------|----------------------------|
| macOS    | Yes | Yes |
| Linux    | Yes | Yes |
| Windows  | No  | Yes |

## Development

```bash
git clone https://github.com/obris-dev/obris-cli.git
cd obris-cli
uv sync
```

Run commands locally without installing:

```bash
uv run obris auth --key <your-api-key> --base http://localhost:8000
uv run obris capture
uv run obris topic list
```

### Publishing

```bash
make publish   # build and publish to PyPI
```

## Privacy Policy

This CLI sends your Obris API key to the Obris API (`api.obris.ai`) to authenticate requests. It uploads files and retrieves topic and knowledge data from your account. No data is stored beyond the local config file at `~/.obris/config.json`.

For the full privacy policy, see [obris.ai/privacy](https://obris.ai/privacy).

## Support

For issues or questions, contact [support@obris.ai](mailto:support@obris.ai) or open an issue on [GitHub](https://github.com/obris-dev/obris-cli/issues).

## License

MIT