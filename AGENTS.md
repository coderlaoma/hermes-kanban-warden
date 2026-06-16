# AGENTS.md

Guidance for generic AI coding agents working in this repository.

## Project background and mission

`kanban-warden` is a Hermes Agent plugin for safer Kanban worker output. The current implementation watches Hermes Kanban coordination tool calls and warns when durable task comments, completions, blockers, or metadata appear to contain secrets or unsafe connection details.

The current repository is narrower than a full Kanban supervisor. It is a non-blocking security guard plugin, not a task dispatcher and not a replacement for Hermes core. Future work may expand it toward broader warden behavior, such as board health watching, leader locking, event tailing, and automated remediation, but those features are not implemented unless corresponding code and tests are added.

## Core design principles

Follow these principles for all changes:

- Plugin-style integration: integrate through Hermes plugin hooks and packaging entry points instead of invasive Hermes core edits.
- Low intrusion: the plugin should warn and guide agents without silently changing user data or blocking unrelated tool calls.
- Default board awareness: if broader board watching is added later, make the normal path observe the default Hermes Kanban board while allowing explicit configuration overrides.
- Leader lock: any future long-running watcher or supervisor must ensure only one active warden instance acts on the same board at a time.
- Event tail plus health sweep: future board-watching behavior should combine incremental event processing with periodic full-board health checks.
- Bounded retries, timeouts, and loop prevention: every automated action must have a ceiling and must avoid repeatedly re-triggering itself.
- Dry-run first: new remediation workflows should default to preview/dry-run behavior before mutating durable board state.
- No secret logging: never log or persist raw tokens, credentials, private keys, or connection strings.
- Auditability: warnings and future automated actions should include enough redacted context for a human to understand what happened.

## Agent workflow expectations

Before editing:

1. Read `README.md`, `pyproject.toml`, and this `AGENTS.md`.
2. Inspect the current tree with Git status so you do not overwrite unrelated work.
3. Keep changes focused on the assigned task.
4. Do not invent commands, package names, paths, or behavior that is not present in the repository.

While working:

- Preserve the non-blocking plugin posture unless the task explicitly changes it.
- Keep findings redacted; tests may use synthetic placeholders but must not contain real credentials.
- Update tests when changing scanner rules, warning text, hook registration, or packaging metadata.
- Prefer small, reviewable changes and document any assumptions.

Before handing off:

- Run the relevant safe checks listed below when tooling is available.
- Report changed paths, exact verification commands, and results.
- If a section of this file becomes stale, update it in the same change.

## Repository organization

Current confirmed layout:

- `README.md` — project overview, install notes, development commands, and security posture.
- `pyproject.toml` — setuptools package metadata, Hermes plugin entry point, dependencies, pytest/ruff/mypy configuration.
- `LICENSE` — project license.
- `src/kanban_warden/__init__.py` — Hermes plugin hook registration and Kanban tool argument extraction.
- `src/kanban_warden/warden.py` — secret scanner, YAML rule loading, redaction, and warning rendering.
- `src/kanban_warden/rules.yaml` — packaged detection rules and allowlist values.
- `src/kanban_warden/plugin.yaml` — directory-plugin metadata for Hermes.
- `src/kanban_warden/py.typed` — marker for typed package consumers.
- `tests/test_warden.py` — scanner and plugin-result transformation tests.
- `src/kanban_warden.egg-info/` — generated packaging metadata. Avoid editing generated metadata directly unless the task explicitly concerns packaging artifacts.

Currently absent or not documented as first-class project areas:

- No `docs/` directory.
- No `scripts/` directory.
- No `Makefile` or `justfile`.
- No implemented leader-lock, event-tail, health-sweep, or board-remediation service yet.

## Development and test commands

Commands documented by the repository:

```sh
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest
python -m build
```

Use these only in an appropriate Python environment. The repository currently includes a `.venv/` on the development host; do not assume it exists elsewhere or commit environment-specific files.

Safe lightweight checks for documentation-only edits:

```sh
test -f AGENTS.md
python -m pytest
python -m ruff check .
```

Run `python -m mypy src` and `python -m build` when changing typed Python code, packaging, or release metadata. If tooling is missing, report the missing command instead of inventing a substitute.

## Safety rules

- Tokens and secrets: never commit credentials, print secret values, or include raw tokens in logs, task comments, fixtures, or examples.
- Test data: use clearly fake synthetic values only, and assert that warnings do not echo the raw secret-like value.
- Hermes core changes: do not edit Hermes core from this repository unless a task explicitly scopes that integration and explains the safety plan.
- Database writes: current code should not write to the Kanban database. Treat any future database write as a sensitive side effect requiring dry-run behavior, idempotency, and audit trail.
- Idempotency: future remediation must avoid duplicate comments, endless task creation, repeated resets, and retry loops.
- Dry-run behavior: new supervisor actions should expose a dry-run preview before making board changes.
- Audit trail: when the warden changes durable board state in future work, record the redacted condition detected, action taken, and guardrails applied.
- Loop prevention: automated recovery must not create infinite task/retry/comment loops.
- Timeouts and retries: external calls, subprocesses, and board scans must have bounded runtime and retry counts.
- Sensitive payloads: sanitize board event bodies, environment dumps, stack traces, and subprocess output before logging.

## Recommended future task decomposition

For broader warden development, split work into focused tasks:

- Scanner quality: tune `rules.yaml`, allowlist behavior, and false-positive coverage.
- Plugin integration: harden Hermes hook registration and compatibility with supported Hermes versions.
- Configuration: add explicit controls for enabled tools, rule files, severity thresholds, and warning behavior.
- Board access layer: if future supervision needs board reads/writes, add safe query helpers and explicit write primitives.
- Leader lock: add single-active-instance coordination and stale-lock handling for any future daemon/watcher.
- Event tailer: add incremental event processing with checkpointing.
- Health sweep: add periodic detection of stale runs, stuck tasks, retry exhaustion, and orphaned locks.
- Remediation policy: add dry-run decisions, bounded retries, loop prevention, and human-readable audit comments.
- Tests: add unit tests for scanner/policy logic and integration-style tests against temporary board databases when board access exists.
- Documentation: keep README quickstart, operational notes, and examples current.

## Maintenance rules

- Keep README and `AGENTS.md` aligned with the real project shape.
- Replace provisional future-supervisor notes with concrete paths and commands as soon as implementation lands.
- Remove stale instructions promptly; misleading agent guidance is worse than no guidance.
- When changing safety-sensitive behavior, update docs and tests in the same change so future agents understand the guardrails.
