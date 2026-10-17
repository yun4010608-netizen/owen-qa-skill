# Functional probes by surface

Pick the sections for the surfaces in your test plan. Each item is a probe; record the command and the result for anything that fails.

## Contents

- [HTTP and gRPC APIs](#http-and-grpc-apis)
- [Web UI](#web-ui)
- [CLI](#cli)
- [Workers and queue consumers](#workers-and-queue-consumers)
- [Scheduled jobs](#scheduled-jobs)
- [Webhooks](#webhooks)
- [Database migrations](#database-migrations)
- [Infrastructure code](#infrastructure-code)

## HTTP and gRPC APIs

Send traffic through the entry point users hit (gateway, ingress, load balancer). Go straight to one instance only when you need to isolate it.

- **Critical flows:** run each flow end to end (create, read, update, delete, or the domain equivalent) and confirm the effect in the data store, not just the response code.
- **Input edges:** missing fields, extra fields, wrong types, empty strings, very long strings, Unicode and emoji, zero, negative and boundary numbers, very large payloads, malformed JSON, wrong `Content-Type`. Expect a 4xx with a useful message. A 5xx or a stack trace in the body is a finding.
- **Authentication:** no credentials, expired token, malformed token, token signed with the wrong key, `alg: none`. If the code or config has a default or placeholder secret (`change-me`, `secret`, `dev`), try to forge a token with it; if the running service accepts it, that is Critical.
- **Authorization:** fetch or change another user's or tenant's resource by ID, call admin endpoints as a normal user, check that list endpoints filter by tenant.
- **Retries and idempotency:** repeat the same write. With an idempotency key, there should be one effect and the same response. Send the repeat to a different instance as well.
- **Concurrency:** send N identical writes at once, spread across instances, then count the side effects in the store (rows, messages, emails, charges). Check-then-insert without a unique constraint and in-memory locks both fail here.
- **Lists:** pagination boundaries, empty results, sorting and filtering with odd values, very large page sizes.
- **Dependency errors and timeouts:** a slow or failing dependency should give a bounded response time and a clear 5xx (503 for unavailable), not a hung connection or a leaked internal error.
- **Health endpoints:** readiness should fail when the service cannot do its job (a required dependency is down). Liveness should not check dependencies, or a database blip restarts every pod at once. A health endpoint that returns 200 while the service cannot serve requests is a finding.

## Web UI

With a browser tool:

- Walk each critical flow as a user would. Watch the console for errors and the network panel for failed requests.
- Forms: validation messages, double-click on submit, back button and refresh after submit, very long input.
- Sessions: expiry in the middle of a flow, two tabs at once, logout in one tab.
- Mobile viewport for the main pages, broken links and images, loading and error states (block an API call and see what the page shows).

Without a browser tool, request the pages and assets, check status codes and that forms post to working endpoints, and say in the report that the UI was not exercised.

## CLI

- `--help` for the tool and each subcommand; every documented flag.
- Exit codes: 0 on success, non-zero on failure. Errors go to stderr, results to stdout.
- Non-interactive use: no TTY, piped input and output, missing config, missing or wrong environment variables.
- Interruption: Ctrl-C (SIGINT) in the middle of a write. Look for partial state, leftover lock files, and whether a re-run recovers.
- Two copies at once against the same state.
- Re-running the same command is safe (idempotent) or refuses clearly.

## Workers and queue consumers

- **Ack timing:** the message is acknowledged after the work is done, not when it is received. Kill the worker mid-job (see resilience.md): the job should run again, not vanish or stay `processing` forever.
- **Idempotency:** processing the same message twice has the same effect as processing it once.
- **Poison messages:** one message that always fails must not block the queue or crash-loop the worker. It should go to a dead-letter queue or be recorded and skipped.
- **Timeouts:** visibility timeout, prefetch, and lease lengths against the longest job. A job longer than its visibility timeout gets delivered to a second worker while the first is still running.
- **Several consumers:** two or more workers never process the same job at the same time.
- **Backlog:** a burst of messages drains in reasonable time; memory stays bounded.

## Scheduled jobs

- With two or more instances, each scheduled run happens once (leader election, a lock, or an external scheduler). In-process schedulers run once per instance.
- A run that takes longer than the interval does not overlap with the next run, or overlapping is safe.
- After downtime, missed runs are handled in a defined way (skipped or caught up).
- Time zones and daylight saving changes, if schedules are local time.

## Webhooks

Incoming:

- Requests with a missing or wrong signature are rejected; the signature check uses the raw body.
- The same delivery sent twice causes one effect. Out-of-order deliveries are handled.
- The handler responds quickly and does slow work asynchronously, so the sender does not time out and retry.

Outgoing:

- Retries with backoff when the receiver is down or slow; a bounded timeout; no secrets in payloads or URLs.

## Database migrations

- Run against a copy with realistic data volume. Note how long tables stay locked.
- Running the migration a second time does nothing.
- During a rolling deploy, the old version of the app keeps working against the new schema (expand first, contract in a later release).
- A rollback path exists, or the report says there is none.

## Infrastructure code

- Terraform or OpenTofu: `plan` right after `apply` shows no changes. `validate` and the project's linters pass. No secrets in plain variables or committed state.
- Helm and Kustomize: render the templates (`helm template`, `kustomize build`) and validate them against the cluster's API versions (`kubeconform` if available).
- In a disposable account or cluster: destroy and recreate, then confirm that the app comes back with its data.
