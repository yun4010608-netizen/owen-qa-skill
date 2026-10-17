# ops-qa

[한국어](README.ko.md)

A QA skill for Claude Code that tests your app the way it runs in production: several instances, real dependencies, and restarts, crashes, and outages while work is in flight.

Most QA clicks through the happy path on a single instance. The bugs that reach production usually live somewhere else: an idempotency key kept in process memory that lets two instances charge twice, a job lost because the worker popped it before a restart, a worker that never reconnects after a 30-second database blip, a health check that says "ok" while every request fails. `/qa` looks for those on purpose and backs every finding with the command and output that show it.

## What it does

1. **Scope.** Reads how the target is built and run, and lists its surfaces, its state, and every time limit (timeouts, TTLs, credential lifetimes, grace periods). Writes the invariants that must survive any fault, then a short test plan.
2. **Run it like production.** Two or more instances of each stateless service, with real databases, queues, and caches.
3. **Baseline.** The project's own build, tests, and linters.
4. **Functional probes** for APIs, web UIs, CLIs, workers, scheduled jobs, webhooks, migrations, and infrastructure code.
5. **Resilience probes.** Rolling restart under load, SIGTERM and SIGKILL mid-job, dependency outages, identical requests across instances, and time-limit mismatches. At `deep`, also duplicate delivery, old and new versions side by side, scale events, and added latency.
6. **Deployment config review**, checked against what the probes observed.
7. **Report.** A verdict, findings by severity with exact repro commands, a coverage table, and what was cleaned up.
8. **Fix mode** (opt-in). A failing test first, then the fix, then the probe again.

## Install

As a plugin:

```
/plugin marketplace add yun4010608-netizen/ops-qa
/plugin install ops-qa@ops-qa
```

Or copy `skills/qa` to `~/.claude/skills/qa` (all projects) or `.claude/skills/qa` (one project).

## Usage

```
/qa quick                # about 10 minutes: the biggest risks, short answer
/qa                      # standard, about 30 to 45 minutes: full report
/qa deep                 # no time limit: every scenario, evidence appendix, residual risks
/qa fix                  # report, then fix with a regression test per finding
/qa http://localhost:8080
```

| Depth | Time | What runs | Report |
|---|---|---|---|
| `quick` | about 10 min | main flow, static multi-instance scan, up to 3 resilience probes picked by risk | verdict, top findings, what was not checked |
| `standard` | 30 to 45 min | all changed or critical surfaces, core resilience scenarios, config review | full report with invariants and coverage |
| `deep` | no limit | every surface and dependency, full fault matrix, sustained load, repeated probes | full report plus evidence appendix, residual risks, fix plan |

Plain requests work too: "quick sanity check before I deploy" runs `quick`, "test this as thoroughly as you can" runs `deep`.

Installed as a plugin, the command is `/ops-qa:qa`. Claude also uses the skill when you ask things like "is this ready to deploy?" or "can a worker restart lose jobs?".

## Safety

- Everything runs under its own Compose project or namespace, so your running stack is never scaled, restarted, or torn down.
- Destructive steps (killing processes, stopping dependencies, injecting faults) run only on environments the skill created or that you call disposable. It asks before each destructive step on anything shared, and stays read-only on production unless you approve each step.
- Cleanup removes only what the run created. It records existing containers, images, and volumes first and never prunes.
- Secret values are kept out of reports and logs.
- No telemetry. The skill makes no network calls of its own. The one bundled script, `scripts/load.py`, uses only the Python standard library and talks only to the targets you pass it.

## Requirements

- Claude Code
- Python 3.8 or newer for `load.py`
- Whatever runs your target: Docker with Compose, `kubectl`, or plain processes
- Optional: a browser MCP server (Playwright or Chrome DevTools) for testing web UIs

## Evals

`evals/fixtures/orders-service` is a small order service with nine known bugs, and `evals/evals.json` holds the prompts and the answer key. Use them to check that a change to the skill still finds what it should.

## License

[MIT](LICENSE)
