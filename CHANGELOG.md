# Changelog

## 0.1.1

- Configure `prod` and `dev` API keys side by side in `~/.obris/config.json`
- `--env` flag on any command to override the active environment
- `obris env [name]` command to show or set the default environment
- Replace `--base` flag with environment-based config

## 0.1.0 — 2025-03-05

Initial public release.

- `obris auth` — authenticate with your API key
- `obris capture` — take a screenshot and upload it
- `obris upload` — upload any file
- `obris topic list` — list topics or knowledge items
- `obris knowledge move` / `delete` — manage knowledge items
- macOS desktop notifications via `terminal-notifier`
- `--prompt` flag for naming captures via dialog
