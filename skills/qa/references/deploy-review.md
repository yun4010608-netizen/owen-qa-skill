# Deployment config and multi-instance code review

Check these against the project's config and code, and against what the resilience probes showed. A config line that contradicts observed behavior is the strongest kind of finding.

## Kubernetes (raw manifests, Helm, Kustomize)

Render first (`helm template`, `kustomize build`) and review the output, not the templates.

- **Replicas:** two or more for stateless services. A PodDisruptionBudget, and anti-affinity or topology spread so replicas do not share a node.
- **Probes:** readiness reflects whether the pod can serve, including required dependencies. Liveness checks only the process itself. Slow starters have a startupProbe instead of a long initialDelaySeconds.
- **Shutdown:** `terminationGracePeriodSeconds` is at least the longest request or job drain observed. A short `preStop` sleep (5 to 10 seconds) lets the pod leave the endpoints list before the process stops. The app handles SIGTERM.
- **Rollout:** RollingUpdate with `maxUnavailable: 0` and `maxSurge` of at least 1 for zero-downtime deploys. `Recreate` only where it is required, with a reason.
- **Resources:** requests and limits set; the memory limit sits above the usage observed under load.
- **Security context:** `runAsNonRoot`, `readOnlyRootFilesystem` where possible, `capabilities.drop: [ALL]`, no `privileged`, no `hostPath` without a reason.
- **Secrets:** come from Secrets or an external store, not plain values in manifests or ConfigMaps. No default or placeholder values (`change-me`) in what gets deployed.
- **Autoscaling:** an HPA has its metrics source available and `minReplicas` of at least 2.
- **Singletons:** components that must run once (schedulers, migrations, leaders) are explicitly singletons: leader election, a Job, or one replica with a stated reason.
- **Images:** pinned tags or digests, not `latest`.
- **Jobs and CronJobs:** `concurrencyPolicy: Forbid` where overlapping runs are unsafe; `backoffLimit`; `activeDeadlineSeconds` that fits inside credential lifetimes.

## Docker Compose

- `healthcheck` on each service, and `depends_on` with `condition: service_healthy`.
- `restart` policy set; `stop_grace_period` long enough for draining.
- No fixed host port on services that are meant to scale.
- Ports for databases, caches, and admin UIs bound to `127.0.0.1`, not all interfaces.
- `init: true` or a real init in the image when the app does not handle signals as PID 1.

## Code that breaks with more than one instance

Search the code for state that only one process can see. Each hit is a candidate for the concurrency and restart probes:

- Module-level or static mutable state used as a cache, session store, idempotency store, rate limiter, counter, or queue: global dicts and lists in Python, module-level `Map` or objects in Node, static maps in Java and C#, package-level maps in Go.
- In-process locks guarding shared resources: `threading.Lock`, `asyncio.Lock`, `synchronized`, `sync.Mutex`, `Mutex` in Rust. They only protect against threads in the same process.
- In-process schedulers without leader election: APScheduler, Celery beat running in every replica, `node-cron`, Spring `@Scheduled`, goroutine tickers.
- Local disk used for shared state: uploads, generated files, SQLite, file locks.
- Sessions in memory, or sticky sessions required for correctness.
- Check-then-act sequences against the database without a unique constraint, `SELECT ... FOR UPDATE`, or a conditional write.
- Work taken off a queue before it is done (`LPOP`, `BRPOP`, auto-ack) with nothing that recovers it after a crash.
- Background threads started at import time, which run in every worker process.
