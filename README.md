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
uv run obris capture                  # screenshot + upload to Scratch
uv run obris capture --prompt         # prompt for a name via dialog
uv run obris capture --name "my pic"  # explicit name
uv run obris upload <file> --topic <id>
uv run obris topics list
uv run obris scratch list
uv run obris move <knowledge_id> --topic <id>
```
