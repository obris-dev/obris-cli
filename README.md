# obris-cli

Capture and upload client for the Obris API.

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```
uv run obris --help
```

## Auth

```
uv run obris auth --key <your-api-key>
```

## Commands

```
uv run obris capture                  # screenshot + upload to Scratch
uv run obris capture --auto-name      # auto-generate name
uv run obris upload <file> --topic <id>
uv run obris topics list
uv run obris scratch list
uv run obris move <knowledge_id> --topic <id>
```