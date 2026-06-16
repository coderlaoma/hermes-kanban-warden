# hermes-kanban-warden

`hermes-kanban-warden` is an MVP Hermes Agent plugin for Kanban boards. It watches Kanban task events, keeps persistent cursors, detects review/stale/failure situations, queues notification decisions, and can optionally apply small auto-advance state transitions after you have inspected `dry-run` output.

MVP version: `0.1.0`

GitHub: https://github.com/coderlaoma/hermes-kanban-warden

## Project goals

Kanban-driven Hermes deployments can involve multiple profiles, reviewers, and long-running workers. This plugin provides a low-intrusion supervisor layer that helps operators answer:

- Which boards and new task events did the profile see?
- Which implementation cards are blocked for review?
- Which reviewer results should unblock source cards?
- Which running tasks look stale or over their timeout budget?
- Which notifications should be retried later instead of being lost?
- Did durable Kanban comments/results accidentally contain likely secrets?

The MVP is deliberately conservative. `dry-run` is the default posture for auto-advance; real board mutations require explicit configuration.

## Naming map

This project uses `hermes-kanban-warden` as the human-facing display name. The technical slugs are intentionally stable:

- GitHub repository: `coderlaoma/hermes-kanban-warden`
- Python import/config namespace: `kanban_warden`
- Python distribution, CLI command, and Hermes plugin entry point: `kanban-warden`

Do not rename the Python package, entry point, CLI, runtime log prefix, database paths, or config namespace unless a future migration explicitly scopes that breaking change.

## Design overview

The plugin has three cooperating layers:

1. Kanban output scanner
   - Hook-style transform for durable Kanban tool output such as `kanban_comment`, `kanban_complete`, and `kanban_block`.
   - Scans user-visible text for likely secrets or unsafe connection strings.
   - Emits warnings with redacted snippets; it does not preserve raw matched values.

2. Supervisor event collector
   - Starts from Hermes plugin registration when `kanban_warden.enabled` is true.
   - Uses a SQLite leader lock so only one supervisor owner acts at a time.
   - Discovers legacy and named Kanban boards, tails `task_events`, persists per-board cursors, enriches events with task relationships, and runs read-only health sweeps.

3. Notification and auto-advance state machine
   - Plans actions for review-required blocks, reviewer approve/needs-changes outcomes, stale running tasks, worker failures, and retry exhaustion.
   - Uses a durable idempotency store so replayed events do not duplicate reviewer cards, comments, unblocks, or outbox notifications.
   - Queues notification decisions into the warden state DB outbox. Transport delivery is intentionally outside the MVP.
   - Applies Kanban board mutations only when `auto_advance.enabled: true` and `auto_advance.dry_run: false`.

## Installation from a checkout

Recommended for development:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Runtime-only install:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Build artifacts:

```bash
. .venv/bin/activate
python -m build
```

Hermes discovers the plugin through the `hermes_agent.plugins` entry point named `kanban-warden`.

## Enable the Hermes plugin

Merge this into the target Hermes profile `config.yaml`:

```yaml
plugins:
  enabled:
    - kanban-warden

kanban_warden:
  enabled: true
  boards: "*"
```

Then restart that Hermes CLI/gateway/profile process so plugin discovery and profile config are reloaded.

A complete sample is in `examples/config.yaml`.

## Configuration example

```yaml
plugins:
  enabled:
    - kanban-warden

kanban_warden:
  enabled: true
  boards: "*"

  leader_lock:
    enabled: true
    lease_seconds: 60
    heartbeat_seconds: 20
    db_path: null

  loop:
    event_interval_seconds: 5
    health_sweep_seconds: 60

  state_db_path: null
  hermes_home: null
  log_level: INFO

  notifications:
    enabled: true
    channels:
      - origin
    review_required: true
    stale_tasks: true
    crash_alerts: true

  auto_advance:
    enabled: false
    dry_run: true
    review_required: true
    stale_claims: true
    reviewer_assignee: reviewer

  limits:
    max_retries: 2
    task_timeout_seconds: 14400
    stale_claim_seconds: 3600
```

Key settings:

- `kanban_warden.enabled`: starts the background supervisor at plugin registration.
- `kanban_warden.boards`: `"*"` discovers all visible boards; a list pins specific board names.
- `leader_lock.enabled`: protects against duplicate supervisors. `lease_seconds` controls lock expiry; `heartbeat_seconds` controls refresh cadence.
- `loop.event_interval_seconds`: event polling interval for the background loop.
- `loop.health_sweep_seconds`: interval for stale/health checks.
- `notifications.*`: controls which decisions are queued to the durable outbox.
- `auto_advance.enabled`: master switch for applying state-machine actions.
- `auto_advance.dry_run`: when true, plans actions without mutating Kanban boards.
- `limits.max_retries`: retry budget before escalation.
- `limits.task_timeout_seconds`: long-running task timeout threshold.
- `limits.stale_claim_seconds`: heartbeat/claim staleness threshold.

## CLI usage

The package installs `kanban-warden` for inspection and smoke testing.

```bash
kanban-warden --config examples/config.yaml status
kanban-warden --config examples/config.yaml dry-run
kanban-warden --config examples/config.yaml run-once
kanban-warden demo-lock
```

`status` prints effective config, leader-lock state, runtime metadata, and policy settings.

`dry-run` runs one collection pass with auto-advance forced into dry-run mode. It prints JSON containing discovered boards, cursor movement, recent events, relationship summaries, health findings, planned actions, action results, and the warden state snapshot.

`run-once` runs one collection pass using the supplied config. It may mutate Kanban boards only if both `auto_advance.enabled: true` and `auto_advance.dry_run: false` are set.

`demo-lock` shows that two independent owners cannot both hold the active leader lease:

```json
{
  "active": true,
  "active_owner": "demo-profile-a",
  "first_acquired": true,
  "second_acquired": false
}
```

## Verification script

Run the MVP verification script in the development environment:

```bash
. .venv/bin/activate
python scripts/verify_mvp.py
```

The script creates a disposable Kanban database and verifies:

- event collection and persistent cursors;
- relationship inference from `task_links`;
- dry-run planning for notify, reviewer creation, comments, unblocks, and retry;
- real-schema reviewer/comment/unblock mutations when dry-run is disabled;
- durable notification outbox entries;
- idempotency on repeated collection; and
- active leader lock status.

A successful run prints JSON with `"ok": true` and explanatory counts.

Development checks:

```bash
. .venv/bin/activate
pytest
ruff check .
mypy src
python -m build
```

## Safety and security

- Scanner findings never include raw matched secrets; snippets are redacted.
- The scanner is conservative and can produce false positives. Treat warnings as a prompt to review durable Kanban output.
- `dry-run` should be inspected before enabling real auto-advance.
- Real board mutations are small and idempotent, but they still affect shared Kanban state.
- Do not store tokens, private keys, passwords, raw database URLs, or personal credentials in config files, README examples, task comments, or run metadata.
- `examples/config.yaml` contains placeholders and safe defaults only.

## Notification reliability boundary

The MVP queues notification decisions into the local warden state DB outbox. It does not guarantee end-user delivery through a real gateway transport.

Known operational boundary: WeChat/iLink gateway rate limits can cause notifier backoff and retries. Warden can preserve notification intent and state-machine decisions, but final user-visible delivery must be validated against the real gateway behavior in the target deployment.

## Troubleshooting

No boards discovered:
- Confirm `kanban_warden.boards` is `"*"` or names the target board.
- Confirm the running profile has the expected `HERMES_HOME` or set `kanban_warden.hermes_home` explicitly.
- Run `kanban-warden --config examples/config.yaml dry-run` and inspect `boards`.

Supervisor does not start:
- Confirm the package is installed in the Python environment used by Hermes.
- Confirm `plugins.enabled` includes `kanban-warden`.
- Confirm `kanban_warden.enabled: true`.
- Restart the Hermes process after changing plugin config.

Duplicate actions or missing actions:
- Inspect `state_db_path` and the `state` section from `status`/`dry-run`.
- Verify all supervisor instances share the intended state DB and leader-lock DB.
- Check whether a previous dry-run advanced event cursors before a later apply run.

Real mutations did not happen:
- `auto_advance.enabled` must be true.
- `auto_advance.dry_run` must be false.
- The action must not already be marked done in the idempotency store.
- The current Kanban schema must contain the required columns used by the action path.

Secret scanner warning appears:
- Replace raw credentials with `[REDACTED]`.
- Prefer stable references such as secret names or vault paths instead of values.

## MVP limitations

- Notification transport delivery is not implemented; decisions are queued in a durable outbox.
- State-machine policies are intentionally narrow and focused on common Kanban workflow events.
- The plugin depends on current Hermes Kanban SQLite schema details for mutation paths.
- There is no packaged migration system for future state DB schema changes yet.
- Multi-profile production rollout should validate leader-lock and state DB paths per deployment topology.

## Suggested next iterations

1. Add an outbox drainer that integrates with Hermes gateway delivery and records retry/backoff results.
2. Add config validation with clearer startup errors for invalid policy combinations.
3. Add state DB migrations and version reporting.
4. Add integration tests against a live Hermes Kanban board fixture.
5. Add operator dashboards or concise status summaries for pending outbox items and retry exhaustion.
EOF'
