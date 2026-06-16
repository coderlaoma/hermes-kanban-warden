# Kanban Warden

Kanban Warden is a small Hermes Agent plugin that watches durable Kanban task output for likely credential leaks. It is designed for worker profiles that write summaries, comments, blockers, and metadata into a shared Kanban database.

The plugin is intentionally non-blocking: it does not stop the Kanban tool call. Instead it appends a redacted warning to the tool result so the agent can correct its output and avoid preserving raw secrets.

## What it checks

Kanban Warden scans these Hermes tools:

- `kanban_comment`
- `kanban_complete`
- `kanban_block`

It inspects user-visible text fields such as `body`, `summary`, `result`, `reason`, and JSON-serialized `metadata`.

Packaged rules detect common high-risk patterns, including:

- token/API key assignments
- GitHub, Slack, and OpenAI-style tokens
- JWT-like bearer tokens
- PEM private key headers
- database URLs and generic URLs containing inline credentials

Allowed placeholders such as `[REDACTED]` and `<redacted>` are ignored.

## Install from a checkout

```bash
python -m pip install .
```

Hermes discovers the plugin through the `hermes_agent.plugins` entry point named `kanban-warden`.

## Directory plugin form

If using Hermes directory plugins instead of Python packaging, copy the package directory or place a plugin directory containing `plugin.yaml` and `__init__.py` under:

```text
~/.hermes/plugins/kanban-warden/
```

Then enable it with the normal Hermes plugin command for the active profile.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest
python -m build
```

## Security posture

Kanban Warden never returns raw matched secrets. Findings include only rule id, severity, location, and a redacted snippet. The scanner is conservative and may produce false positives; warnings should be treated as prompts to review and redact durable Kanban output.
