# Resilience probes

How to run the target with several instances, how to inject each fault, and what counts as a pass.

## Contents

- [Environments](#environments): Docker Compose, Kubernetes, bare processes
- [Driving traffic and jobs](#driving-traffic-and-jobs)
- [Scenarios](#scenarios)
- [Checking invariants](#checking-invariants)

## Environments

### Docker Compose

- Scale: `docker compose up -d --build --scale api=2 --scale worker=2`.
- A service with a fixed host port (`"8080:8080"`) cannot run twice. Either use a port range (`"127.0.0.1:8080-8081:8080"`) so each replica gets its own port, or reach the replicas from inside the compose network. If the project's compose file blocks scaling, record it as a finding and work around it in a copy, not in the original file (`docker compose -f compose.yaml -f "$QA_DIR/override.yaml"`).
- List replicas: `docker compose ps --format '{{.Name}}' api`.
- Run tools inside the network, where the service name resolves to all replicas: `docker run --rm --network <project>_default -v <skill-dir>/scripts:/qa:ro python:3.13-slim python3 /qa/load.py --target http://api:8080 ...`.
- Bind ports to `127.0.0.1` so databases and dashboards started for QA are not reachable from the local network.
- Clean up: `docker compose down -v --remove-orphans` (only for a project you started; `-v` deletes its volumes).

### Kubernetes

- Deploy into a namespace you create for the run when you deploy yourself (`kubectl create ns qa-<name>`), and delete it at the end.
- Scale: `kubectl scale deploy/<name> --replicas=2`, then `kubectl rollout status deploy/<name>`.
- `kubectl port-forward` sends everything to one pod. To spread load across replicas, go through the Service from inside the cluster:
  `kubectl run qa-load -n <ns> --rm -i --restart=Never --image=python:3.13-slim -- python3 - <args> < <skill-dir>/scripts/load.py`
  or go through the ingress.
- If the cluster is managed by GitOps (Argo CD, Flux), manual changes get reverted, sometimes in the middle of a test. Pause auto-sync for the app, or test in a separate namespace, and restore auto-sync afterwards.

### Bare processes

Start two copies on different ports with the same configuration and dependencies, and pass both to `load.py` with `--target` twice. Note in the report that there was no load balancer in front.

## Driving traffic and jobs

`scripts/load.py` sends requests at a steady rate and prints a failure timeline:

```bash
python3 <skill-dir>/scripts/load.py --target http://localhost:8080 --target http://localhost:8081 \
  --path /orders --method POST --json '{"item":"qa-{n}","qty":1}' \
  --concurrency 8 --duration 90 --out "$QA_DIR/run.csv" > "$QA_DIR/run.txt" &
```

- `{n}` and `{uuid}` make each request unique. Use a constant value (for example `--header 'Idempotency-Key: same-1'`) to send identical requests on purpose.
- If responses carry an instance header (`X-Instance`), the summary shows how requests were spread. Otherwise check the logs of each instance.
- For queue workers, enqueue jobs whose duration you control, so you can kill a worker while it is in the middle of one. Prefer the app's own API for enqueueing; publish directly to the queue only if there is no API.
- Note the 2xx count from the run. Every accepted request should show up later in the store.

## Scenarios

Each scenario: start traffic or jobs, inject the fault, wait for recovery, stop traffic, let queues drain, then check the invariants. Record the timeline (fault injected at t+X, recovered at t+Y).

### Rolling restart under load

- Compose: restart replicas one at a time, waiting for each to be healthy:
  `for c in $(docker compose ps -q api); do docker restart -t 30 "$c"; until [ "$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo running)" != starting ]; do sleep 1; done; done`
  Without a load balancer in front, the client sees the restarting replica as connection errors; say so rather than blaming the app.
- Kubernetes: `kubectl rollout restart deploy/<name> && kubectl rollout status deploy/<name>`.
- Pass: no failed requests through the load balancer, or only failures that the documented client retry absorbs; no stuck work.
- Typical bugs: no readiness probe, so traffic reaches a pod that is still starting; no SIGTERM handling, so in-flight requests are cut; no preStop delay, so the pod stops before it leaves the endpoints list; `maxUnavailable` too high.

### Graceful shutdown

- Start a long request or job, find the instance that is handling it (logs, `X-Instance`, or the job's worker field), then send SIGTERM:
  - Compose: `docker kill -s TERM <container>`, then measure how long the container takes to exit (`docker wait`).
  - Kubernetes: `kubectl delete pod <pod>` (normal grace period).
- Pass: in-flight work finishes within the grace period or is handed back (nack or requeue); no new work is accepted after SIGTERM; the process exits on its own before SIGKILL.
- Typical bugs: the process ignores SIGTERM (a program running as PID 1 with no handler ignores it, so the platform waits out the grace period and then SIGKILLs it); the worker picks up new jobs after SIGTERM; the grace period is shorter than the longest job.

### Crash mid-work

- Kill the instance that holds a job or a lock, with no chance to clean up:
  - Compose: `docker kill -s KILL <container>`.
  - Kubernetes: `kubectl delete pod <pod> --grace-period=0 --force`. On kind or minikube you can also kill the process on the node (`docker exec <node> pkill -9 -f <process>`). Sending `kill -9 1` from inside the container does not work: the kernel protects PID 1 from signals sent inside its own namespace.
- Pass: the job runs again and its effect happens once; the lock or lease expires and another instance takes over; no partial writes (check that multi-step writes are transactional); nothing stays `running` or `processing` past the maximum job duration.
- Typical bugs: the message was popped or acked before the work was done; a lock without a TTL; status set to `processing` with nothing that ever resets it.

### Dependency outage and recovery

- Compose: `docker compose stop <db|queue|cache>`, keep traffic running for 30 to 60 seconds, then `docker compose start <dependency>`.
- Kubernetes: scale the dependency to 0 and back, or block it with a NetworkPolicy if the CNI enforces policies.
- Pass: requests fail fast with a clear error (503) instead of hanging; readiness turns false while liveness stays true; the service recovers on its own after the dependency returns, without a restart; connection pools reconnect; messages accepted before the outage are not lost.
- Typical bugs: a health check that does not touch the dependency; no timeout on the client, so threads pile up; a crash loop because startup requires the dependency; the app caches a dead connection forever.

### Identical requests across instances at once

- Send the same request (same idempotency key, same unique field, or the same "reserve item X" action) from many threads, spread across all instances:
  `load.py --target <a> --target <b> --method POST --path /orders --json '{"item":"x","qty":1}' --header 'Idempotency-Key: dup-1' --concurrency 20 --requests 40`
- Then count side effects in the store.
- Pass: exactly one effect.
- Typical bugs: idempotency keys, locks, rate limits, or caches kept in process memory; check-then-insert without a unique constraint or transaction.

### Time-limit mismatches

- List every time limit that applies to one unit of work: client timeout, load balancer idle timeout, server timeout, job maximum runtime, credential or token lifetime (cloud STS sessions default to one hour), lock and lease TTLs, queue visibility timeout, termination grace period.
- Flag any limit that is shorter than the work it covers. Where config allows, shorten the limit to make it testable (for example a 60-second token with a 90-second job) and confirm what breaks.
- Typical bugs: long jobs fail when credentials expire mid-run; a lock expires while its holder is still working and a second worker starts.

### Duplicate message delivery

- Deliver the same message twice: republish it, or kill the consumer after the side effect but before the ack.
- Pass: one effect. The consumer recognizes the duplicate (a processed-message table, a unique key, or a natural idempotent write).

### Old and new versions together

- Run the previous release and the new build side by side against the same database and queue, and send traffic to both.
- Pass: each version handles data and messages written by the other. Schema changes are backward compatible during the rollout.

### Scale out and in under load

- Add instances during traffic, then remove them. Pass: no errors from new instances that are not ready yet; removed instances drain cleanly; work is redistributed.

### Slow dependency or added latency

- Add latency between the app and a dependency: `tc qdisc add dev eth0 root netem delay 500ms` inside a container that has `NET_ADMIN`, or Toxiproxy if the project already uses it. Remove it afterwards (`tc qdisc del dev eth0 root`).
- Pass: timeouts are bounded, connection pools do not run dry, and the service recovers when the latency goes away.

## Checking invariants

- Query the stores directly: SQL `count(*) ... group by status`, Redis `LLEN` and `HGETALL`, the queue's management API for ready and unacked counts.
- Compare counts: 2xx responses recorded by `load.py`, records in the store, completed jobs, and side effects. They should line up exactly, or the report should explain the difference.
- Look for stuck states, such as `status = 'running' AND updated_at < now() - <max duration>`, and locks whose owner no longer exists.
- Let the system settle (queues drained, retries done) before checking, and record how long that took.
- Save the queries and their output in `$QA_DIR` so the report can quote them.
