# Completed Summary Tail Design

## Goal

When Hermes native Kanban completion notifications truncate a long completion summary, Kanban Warden sends the omitted tail through its existing durable notification outbox.

## Approach

Warden already supplements long blocked reasons with a `blocked_reason_tail` notification. This change adds the same pattern for completed task summaries:

- Detect `task_events.kind = "completed"` with a string `summary` payload longer than the native summary prefix limit.
- Queue one idempotent `notify` action keyed by `completed-tail:<board>:<task_id>:<event_id>`.
- Deliver a `completed_summary_tail` message that contains only the omitted tail, not the full native prefix.
- If the completed task has no direct subscriber, reuse the root or parent task subscriber from the event relationship so root-only Kanban subscriptions still receive the continuation.

The feature remains gated by `notifications.enabled`, `notifications.delivery_enabled`, and the existing subscriber lookup. It does not duplicate short completion messages and still retries when no target, root, or parent subscriber exists.

## Tests

Focused tests cover long completed summaries, short completed summaries, idempotency on repeated collection, and the delivered message body.
