---
name: qa
description: Production-realistic QA for web apps, APIs, CLIs, workers, and services. Runs the target the way it really runs (two or more instances, real databases, queues, and caches), exercises each surface, then restarts, kills, and cuts off dependencies while work is in flight to check that no requests, jobs, locks, or data are lost or duplicated. Produces an evidence-backed report with repro commands, and fixes only when asked. Use this whenever the user asks to QA, test, verify, or bug-hunt an app or service, asks "does this work?" or "is this ready to ship, merge, or deploy?", wants a check before a release or after a change, or worries about restarts, rolling deploys, scaling out, failover, duplicate processing, or lost jobs, even if they never say "QA".
license: MIT
---

# QA

Find out whether the target works the way it will run in production, and back every claim with evidence.

Most bugs that reach production do not live in the happy path on one instance. They appear when two instances sit behind a load balancer, when a deploy restarts pods mid-request, when a worker dies holding a job or a lock, or when the database drops out for thirty seconds. This skill tests those conditions on purpose, alongside ordinary functional testing.

## Options

Take these from the user's request or the skill arguments (`/qa deep fix`, `/qa quick http://localhost:8080`). Use the defaults when nothing is said.

| Option | Values | Default |
|---|---|---|
| depth | `quick`, `standard`, `deep` | `standard` |
| mode | `report` (changes no code), `fix` | `report` |
| target | path, URL, service name, branch, PR, or diff | the current repository; on a feature branch, its diff against the default branch plus whatever calls the changed code |

- `quick`: build, existing tests, smoke test of critical flows, one rolling restart under load.
- `standard`: `quick`, plus functional probes on every changed or critical surface, concurrency across instances, and the core resilience scenarios (graceful shutdown, crash mid-work, outage of the primary data store).
- `deep`: `standard`, plus the full resilience matrix for every stateful dependency, duplicate delivery, old and new versions running together, scale events, slow dependencies, and edge-case sweeps on all surfaces.

## Ground rules

1. **No evidence, no finding.** A finding needs the command you ran and the output you saw. If you suspect a problem but could not reproduce it, put it under "Suspected" with what you tried. A report full of maybes teaches people to ignore reports.
2. **Run it like production.** Run at least two instances of every stateless service, with real dependencies in containers and no mocks for state. A single instance hides in-process caches, locks, sessions, idempotency stores, and schedulers that would run twice. If the target cannot run as two instances (fixed host ports, singleton assumptions, state in local files), that is a finding in itself.
3. **Every state change can lose work.** Restarts, deploys, crashes, scale events, and dependency outages are where requests, jobs, locks, and data get lost or duplicated. Test them while work is in flight, then check the invariants.
4. **Only break what you own.** Killing processes, stopping dependencies, wiping data, and injecting network faults are fine on environments you created for this run or that the user called disposable. On anything shared (a staging cluster, a teammate's environment, a cloud account), ask before each destructive step. Do not touch production unless the user explicitly asks, and even then keep to read-only probes unless they approve each destructive step.
5. **Keep secrets out of the output.** Use the credentials the environment already provides. Do not print secret values into the report, logs, or chat, and redact tokens in captured output.
6. **Report mode changes no code.** Probing still creates containers and test data. Keep a list of what you create so you can remove it.
7. **Clean up**, even if the run stops early. See step 9.

## Workflow

### 1. Scope the target

Read before running anything:

- **How it is built and run:** README, Makefile or Taskfile, package manifests, Dockerfiles, compose files, Helm, Kustomize, or raw Kubernetes manifests, Procfile, CI workflows.
- **Surfaces:** web UI, HTTP or gRPC APIs (routes, OpenAPI specs), CLI entry points, queue consumers, schedulers and cron jobs, incoming and outgoing webhooks, database migrations, infrastructure code.
- **State:** databases, queues, caches, object storage, local files, locks and leases, and in-memory state such as module-level dicts, singletons, and in-process caches or rate limiters.
- **Time limits:** request and job timeouts, credential and token lifetimes, lock and lease TTLs, queue visibility timeouts, termination grace periods. Mismatches between them are a common bug class: a job can run for two hours while its cloud credentials expire after one, a lock TTL is shorter than the work it protects, or the grace period is shorter than the longest request.

Classify the environment as **disposable** (you are about to create it, or the user said so) or **shared**.

Write down the **invariants** before testing: domain statements that must hold after every fault. For example, every accepted order reaches exactly one terminal state; one idempotency key produces one side effect; balances sum to the same total; no lock is held by a dead owner past its TTL; no record stays `running` longer than the maximum job duration. Take them from the domain model and the code, not from a generic list.

Then write a short test plan: surfaces, probes, invariants, and which steps are destructive. Show it to the user and continue without waiting, unless a destructive step targets something shared.

### 2. Bring it up like production

Use the project's own tooling first, then scale every stateless service to at least two instances. Recipes for Docker Compose, Kubernetes, and bare processes are in [references/resilience.md](references/resilience.md) under "Environments".

If all you have is a deployed URL (no code, or no way to run it yourself), treat the environment as shared: run the functional probes black-box, and run resilience probes only with the user's go-ahead for each one.

Create a scratch directory for evidence (`QA_DIR=$(mktemp -d -t qa-XXXXXX)`) and keep raw outputs there. Record the environment: git commit, image tags, instance counts, dependency versions, and any known differences from production.

### 3. Baseline

Run what the project already has: build, unit and integration tests, linters, type checks. Rerun a failing test once to tell flaky from broken. Check the health and readiness endpoints. A failing baseline is a finding, but keep going unless nothing runs at all.

### 4. Functional probes

For each surface in the plan, work through its checklist in [references/surfaces.md](references/surfaces.md). At minimum, cover the critical flows end to end, input edges, authentication and authorization, error handling, retries and idempotency, and identical requests sent concurrently to different instances.

For a web UI, use a browser tool if one is available (Playwright MCP, Chrome DevTools MCP, or a built-in browser). Without one, test the HTTP layer and say in the report that the UI itself was not exercised.

### 5. Resilience probes

For each scenario that applies at the chosen depth: start realistic traffic or jobs, inject the fault, let the system recover, then check the invariants. Commands, pass criteria, and typical bugs for each scenario are in [references/resilience.md](references/resilience.md).

`scripts/load.py` (under this skill's base directory, shown as `<skill-dir>` below; Python standard library only) drives HTTP traffic and prints failures second by second, which shows exactly when a restart dropped requests:

```bash
python3 <skill-dir>/scripts/load.py \
  --target http://localhost:8080 --target http://localhost:8081 \
  --path /orders --method POST --json '{"item":"qa-{n}","qty":1}' \
  --concurrency 8 --duration 60 --out "$QA_DIR/rolling-restart.csv"
```

| Scenario | quick | standard | deep |
|---|---|---|---|
| Rolling restart under load | yes | yes | yes |
| Graceful shutdown (SIGTERM mid-request and mid-job) | | yes | yes |
| Crash (SIGKILL mid-job, while holding a lock) | | yes | yes |
| Dependency outage and recovery | | primary store | every dependency |
| Identical requests across instances at once | | yes | yes |
| Time-limit mismatches | read config | read config, test the shortest | test all |
| Duplicate message delivery | | | yes |
| Old and new versions running together | | | yes |
| Scale out and in under load | | | yes |
| Slow dependency or added latency | | | yes |

Skip a scenario only when it cannot apply (no queue means no duplicate delivery), and say why in the coverage table.

### 6. Review the deployment config

If the project has Kubernetes, Helm, Compose, or similar config, check it against [references/deploy-review.md](references/deploy-review.md), and check it against what you observed. If graceful shutdown took 20 seconds in step 5 and `terminationGracePeriodSeconds` is 10, that is a finding with evidence from both sides. The same file lists code patterns that break with more than one instance.

### 7. Report

Write the report in the language the user writes in. Use this structure:

```markdown
# QA report: <target> (<depth>, <mode>)

Verdict: Ship / Ship with known issues / Do not ship. One sentence on why.

## Environment
- Commit, images, instances per service, dependencies, where it ran
- Known differences from production

## Findings
### [Critical] <what breaks, in user terms>
- Surface / scenario:
- Steps to reproduce: exact commands
- Expected:
- Actual: output excerpt, log lines, status counts
- Likely cause: `path/to/file.py:123`, if you found it
- Suggested fix: one or two lines

## Suspected (not reproduced)
- What you saw, what you tried, why it is not confirmed

## Coverage
| Surface or scenario | Result | Notes |
|---|---|---|
| ... | Pass / Fail / Skipped (why) / N/A | ... |

## Cleanup
What you created and removed, and anything left behind.
```

Sort findings by severity, then by how likely users are to hit them:

- **Critical:** data loss or corruption, a security hole, duplicated side effects that cost money or cannot be undone, a full outage.
- **High:** a common flow fails; work is lost or stuck after a routine restart or deploy; recovery needs manual action.
- **Medium:** degraded behavior with a workaround; errors during restarts that clients retry; health checks that report healthy when the service is not.
- **Low:** cosmetic issues, minor validation gaps, noisy logs.

Save the full report as `$QA_DIR/report.md` next to the evidence. In chat, give the verdict, the finding titles with severities, and the report path.

### 8. Fix mode

Only when the user asked for fixes.

- Work through the report from the most severe finding down.
- For each finding, first write a test that reproduces it and fails. Then fix the code, run that test and the probe that found the problem, and rerun the baseline suite.
- Keep one finding per change. Commit each separately only if the user asked for commits or the repository's conventions call for it; otherwise leave the changes uncommitted and list them.
- If a fix needs a design change (a distributed lock, an idempotent consumer, a schema migration, a new dependency), stop and present the options with their tradeoffs instead of picking one.
- Do not weaken or delete a test to make it pass.
- Update the report: mark each finding Fixed (with the commit or diff) or Not fixed (with the reason).

### 9. Clean up

Stop background load, restart anything you stopped, restore replica counts and config, remove the containers, networks, namespaces, and test data you created, and delete temporary files that hold credentials. Check that the environment is back to how you found it, and list anything you could not restore under "Cleanup" in the report.
