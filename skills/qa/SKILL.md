---
name: qa
description: Production-realistic QA for web apps, APIs, CLIs, workers, and services, at three depths - a quick check that answers in minutes, a standard pass, and an exhaustive deep run. Runs the target the way it really runs (two or more instances, real databases, queues, and caches), exercises each surface, then restarts, kills, and cuts off dependencies while work is in flight to check that no requests, jobs, locks, or data are lost or duplicated. Produces an evidence-backed report with repro commands, and fixes only when asked. Use this whenever the user asks to QA, test, verify, smoke-test, or bug-hunt an app or service, asks "does this work?" or "is this ready to ship, merge, or deploy?", wants a check before a release or after a change, or worries about restarts, rolling deploys, scaling out, failover, duplicate processing, or lost jobs, even if they never say "QA".
license: MIT
---

# QA

Find out whether the target works the way it will run in production, and back every claim with evidence.

Most bugs that reach production do not live in the happy path on one instance. They appear when two instances sit behind a load balancer, when a deploy restarts pods mid-request, when a worker dies holding a job or a lock, or when the database drops out for thirty seconds. This skill tests those conditions on purpose, alongside ordinary functional testing.

## Depth, mode, and target

Pick the depth from the user's words first, then from arguments, then the default.

- **quick**: "quick", "fast", "smoke test", "sanity check", "just the big problems", "빠르게", "간단히", "최소한". The user wants an answer in minutes.
- **standard** (default): no signal either way.
- **deep**: "thorough", "everything", "as detailed as possible", "before a major release", "자세하게", "꼼꼼히", "최대한". The user accepts a long run in exchange for coverage.
- Explicit arguments win: `/qa quick`, `/qa deep fix`, `/qa standard http://localhost:8080`.

| | quick | standard | deep |
|---|---|---|---|
| Goal | the biggest risks, answered fast | a solid pass before a release | everything that can reasonably be tested |
| Time budget | about 10 minutes | about 30 to 45 minutes | no limit; post a one-line progress note after each step |
| 1. Scope | README, run config, the main code path | all surfaces, state, and time limits | the same, plus deployment manifests and a full list of time limits |
| 3. Baseline | build; existing tests only if they finish in about 2 minutes | build, tests, linters | the same, run twice to catch flaky tests |
| 4. Functional | the one or two critical flows | checklists for each changed or critical surface | full checklists for every surface, including auth and input sweeps |
| 5. Resilience | up to 3 probes, picked by risk | the core scenarios | the full matrix for every dependency; repeat each failing probe to confirm it |
| 6. Config review | only what you notice on the way | checked against observed behavior | the full checklist, including security context and secrets |
| 7. Report | short form | full report | full report, evidence appendix, residual risks |

At every depth, spend a minute on the static scan for multi-instance hazards in [references/deploy-review.md](references/deploy-review.md) ("Code that breaks with more than one instance"). It finds things the probes cannot reach in the time available.

Quick depth picks its probes by risk, most likely to find something serious first:

1. If the code keeps state in process memory (idempotency keys, locks, caches, rate limits, schedulers): identical requests across instances.
2. If there is a queue or a background worker: kill a worker mid-job and check that the job is not lost.
3. Otherwise, or if the budget allows: a rolling restart under load.

Keep quick quick. Record the start time (`date +%s`) and check it before each new probe. When the budget is spent, stop and report, and list what you did not check. If you think a deeper run is needed, say so in the report and offer it rather than doing it.

**Mode:** `report` (default) changes no code. `fix` fixes after reporting (step 8).

**Target:** a path, URL, service name, branch, PR, or diff. Default: the current repository. On a feature branch, its diff against the default branch plus whatever calls the changed code.

## Ground rules

1. **No evidence, no finding.** A finding needs the command you ran and the output you saw. If you suspect a problem but could not reproduce it, put it under "Suspected" with what you tried. A report full of maybes teaches people to ignore reports.
2. **Run it like production.** Run at least two instances of every stateless service, with real dependencies in containers and no mocks for state. A single instance hides in-process caches, locks, sessions, idempotency stores, and schedulers that would run twice. If the target cannot run as two instances (fixed host ports, singleton assumptions, state in local files), that is a finding in itself.
3. **Every state change can lose work.** Restarts, deploys, crashes, scale events, and dependency outages are where requests, jobs, locks, and data get lost or duplicated. Test them while work is in flight, then check the invariants.
4. **Work in your own space.** Start what you run under a name that clearly belongs to this QA run: a Compose project such as `qa-<target>-<random>` (`docker compose -p ...`) or a Kubernetes namespace such as `qa-<target>`. Running `--scale`, `restart`, or `down -v` against the user's own Compose project or namespace changes their environment and can delete their data. If the only way to test is the user's existing environment, treat it as shared.
5. **Only break what you own.** Killing processes, stopping dependencies, wiping data, and injecting network faults are fine in the space you created for this run, or in an environment the user called disposable. On anything shared (a staging cluster, a teammate's environment, a cloud account), ask before each destructive step. Do not touch production unless the user explicitly asks, and even then keep to read-only probes unless they approve each destructive step.
6. **Keep secrets out of the output.** Use the credentials the environment already provides. Do not print secret values into the report, logs, or chat, and redact tokens in captured output.
7. **Report mode changes no code.** Probing still creates containers and test data. Keep a list of what you create.
8. **Clean up only what you created.** Record what exists before you start (step 2). At the end, remove what the run created and nothing else. Never remove anything that was there before, including base images, shared build caches, and other projects' volumes, and never run prune commands. If you cannot tell whether something is yours, list it instead of deleting it.

## Workflow

The depth table says how far to go in each step.

### 1. Scope the target

Read before running anything:

- **How it is built and run:** README, Makefile or Taskfile, package manifests, Dockerfiles, compose files, Helm, Kustomize, or raw Kubernetes manifests, Procfile, CI workflows.
- **Surfaces:** web UI, HTTP or gRPC APIs (routes, OpenAPI specs), CLI entry points, queue consumers, schedulers and cron jobs, background threads, incoming and outgoing webhooks, database migrations, infrastructure code.
- **State:** databases, queues, caches, object storage, local files, locks and leases, and in-memory state such as module-level dicts, singletons, and in-process caches or rate limiters.
- **Time limits:** request and job timeouts, credential and token lifetimes, lock and lease TTLs, queue visibility timeouts, termination grace periods. Mismatches between them are a common bug class: a job can run for two hours while its cloud credentials expire after one, a lock TTL is shorter than the work it protects, or the grace period is shorter than the longest request.

Classify the environment as **disposable** (you are about to create it, or the user said so) or **shared**.

Write down the **invariants** before testing: domain statements that must hold after every fault. For example, every accepted order reaches exactly one terminal state; one idempotency key produces one side effect; stock goes down by exactly the quantity of completed orders; each customer gets one confirmation; no lock is held by a dead owner past its TTL; no record stays `running` longer than the maximum job duration. Take them from the domain model and the code, not from a generic list. At quick depth, two or three invariants are enough.

Then write a short test plan: surfaces, probes, invariants, and which steps are destructive. Show it to the user and continue without waiting, unless a destructive step targets something shared.

### 2. Bring it up like production

Create a scratch directory, note the start time, and record what already exists so cleanup can tell your resources from everyone else's:

```bash
QA_DIR=$(mktemp -d -t qa-XXXXXX); date +%s > "$QA_DIR/start"
{ docker ps -a --format '{{.Names}}'; docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}'
  docker volume ls -q; docker network ls --format '{{.Name}}'; } > "$QA_DIR/before.txt" 2>/dev/null
kubectl get ns -o name >> "$QA_DIR/before.txt" 2>/dev/null   # if Kubernetes is involved
```

Use the project's own tooling, under your own project name or namespace (ground rule 4), then scale every stateless service to at least two instances. Recipes for Docker Compose, Kubernetes, and bare processes are in [references/resilience.md](references/resilience.md) under "Environments".

If all you have is a deployed URL (no code, or no way to run it yourself), treat the environment as shared: run the functional probes black-box, and run resilience probes only with the user's go-ahead for each one.

Record the environment: git commit, image tags, instance counts, dependency versions, and any known differences from production. Keep raw outputs in `$QA_DIR`.

### 3. Baseline

Run what the project already has: build, unit and integration tests, linters, type checks. Rerun a failing test once to tell flaky from broken. Check the health and readiness endpoints. A failing baseline is a finding, but keep going unless nothing runs at all.

### 4. Functional probes

For each surface in the plan, work through its checklist in [references/surfaces.md](references/surfaces.md). At standard depth and above, cover the critical flows end to end, input edges, authentication and authorization, error handling, retries and idempotency, and identical requests sent concurrently to different instances. After each flow, check every side effect it should have caused (rows, messages, emails, stock, charges), not just the response.

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
| Identical requests across instances at once | if in-memory state | yes | yes |
| Crash (SIGKILL mid-job, while holding a lock) | if a worker exists | yes | yes |
| Rolling restart under load | if budget allows | yes | yes |
| Graceful shutdown (SIGTERM mid-request and mid-job) | | yes | yes |
| Dependency outage and recovery | | primary store | every dependency |
| Time-limit mismatches | | read config, test the shortest | test all |
| Concurrent work on the same resource (same item, account, row) across workers | | yes | yes |
| Duplicate message delivery | | | yes |
| Old and new versions running together | | | yes |
| Scale out and in under load | | | yes |
| Slow dependency or added latency | | | yes |
| Sustained load for 10 minutes or more | | | yes |

Skip a scenario only when it cannot apply (no queue means no duplicate delivery), and say why in the coverage table.

### 6. Review the deployment config

If the project has Kubernetes, Helm, Compose, or similar config, check it against [references/deploy-review.md](references/deploy-review.md), and check it against what you observed. If graceful shutdown took 20 seconds in step 5 and `terminationGracePeriodSeconds` is 10, that is a finding with evidence from both sides.

### 7. Report

Write the report in the language the user writes in. Save it as `$QA_DIR/report.md` next to the evidence. In chat, give the verdict, the finding titles with severities, and the report path.

**Quick depth** uses the short form, about 40 lines at most:

```markdown
# Quick QA: <target>

Verdict: Ship / Ship with known issues / Do not ship. One sentence on why.

## Top findings
1. [Severity] <what breaks, in user terms>
   - Repro: `<one command>`
   - Saw: <the output line that shows it>
   - Likely cause: `path/to/file.py:123`

## Not checked
- <what a standard or deep run would add>
```

**Standard and deep** use the full form:

```markdown
# QA report: <target> (<depth>, <mode>)

Verdict: Ship / Ship with known issues / Do not ship. One sentence on why.

## Environment
- Commit, images, instances per service, dependencies, where it ran
- Known differences from production

## Invariants
- The statements you checked after each fault

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

Deep depth adds three sections after Coverage:

- **Evidence appendix:** for each finding, the timeline of the probe that found it (fault injected at t+X, recovered at t+Y) and the raw output that proves it.
- **Residual risks:** what could still fail that this run could not test, and why (no production-like data, no second region, no access to the real provider).
- **Fix plan:** the findings grouped into changes, in the order you would make them, with the design decisions each one needs.

Sort findings by severity, then by how likely users are to hit them:

- **Critical:** data loss or corruption, a security hole, duplicated side effects that cost money or cannot be undone, a full outage.
- **High:** a common flow fails; work is lost or stuck after a routine restart or deploy; recovery needs manual action.
- **Medium:** degraded behavior with a workaround; errors during restarts that clients retry; health checks that report healthy when the service is not.
- **Low:** cosmetic issues, minor validation gaps, noisy logs.

### 8. Fix mode

Only when the user asked for fixes.

- Work through the report from the most severe finding down.
- For each finding, first write an automated test that reproduces it and fails. Then fix the code, run that test and the probe that found the problem, and rerun the baseline suite. Leave the tests in the repository so the problem cannot come back unnoticed.
- Keep one finding per change. Commit each separately only if the user asked for commits or the repository's conventions call for it; otherwise leave the changes uncommitted and list them.
- If a fix needs a design change (a distributed lock, an idempotent consumer, a schema migration, a new dependency), stop and present the options with their tradeoffs instead of picking one.
- Do not weaken or delete a test to make it pass.
- Update the report: mark each finding Fixed (with the commit or diff) or Not fixed (with the reason).

### 9. Clean up

Stop background load, restart anything you stopped, and restore replica counts and config. Remove your Compose project (`docker compose -p <your-project> down -v --remove-orphans --rmi local`) or namespace, the test data you created, and temporary files that hold credentials. Then compare against `$QA_DIR/before.txt`: anything new that you can tie to this run can go; anything listed there stays, even if it looks unused. List anything you could not restore or could not attribute under "Cleanup" in the report.
