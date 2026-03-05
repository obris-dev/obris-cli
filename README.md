# obris-cli

Capture and upload client for the Obris API.

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

For macOS notifications with deep linking to uploaded content:

```
brew install terminal-notifier
```

```
uv run obris --help
```

## Auth

```
uv run obris auth --key <your-api-key>
uv run obris auth --key <your-api-key> --base http://localhost:8000  # local dev
```

## Commands

```
uv run obris capture                              # screenshot + upload to Scratch
uv run obris capture --prompt                     # prompt for a name via dialog
uv run obris capture --name "my pic"              # explicit name
uv run obris upload <file> --topic <id>

uv run obris topic list                           # list all topics
uv run obris topic list <topic_id>                # list knowledge in a topic

uv run obris knowledge move <id> --topic <id>     # move knowledge item
uv run obris knowledge delete <id>                # delete knowledge item
```

## Hotkeys

Bind keyboard shortcuts to capture commands using any automation tool — [Alfred](https://www.alfredapp.com/), [Raycast](https://www.raycast.com/), [Keyboard Maestro](https://www.keyboardmaestro.com/), macOS Shortcuts, etc.

### Example: Alfred

Create a workflow with a **Hotkey** trigger connected to a **Run Script** action (language: `/bin/zsh`).

### Quick Capture

```zsh
<path/to/uv> --directory <path/to/obris-cli> run obris capture
```

### Capture with Name Prompt

```zsh
<path/to/uv> --directory <path/to/obris-cli> run obris capture --prompt
```

> **Tip:** Use full paths since Alfred doesn't load your shell profile. Run `which uv` to find your uv path.