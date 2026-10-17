#!/usr/bin/env python3
"""Drive steady HTTP traffic and show when and how requests failed.

Run it during a restart, crash, or outage. The per-second failure timeline
shows exactly which window dropped requests. Standard library only.

Example:
  python3 load.py --target http://localhost:8080 --target http://localhost:8081 \
      --path /orders --method POST --json '{"item":"qa-{n}","qty":1}' \
      --concurrency 8 --duration 60 --out /tmp/qa/run.csv

Placeholders in --path, --json, --data and --header values:
  {n}     sequence number, unique per request within this run
  {uuid}  random UUID per request
Use a fixed value instead (for example a constant Idempotency-Key header)
to send identical requests on purpose.

The last line of output is "SUMMARY {json}" for scripts to parse.
"""

import argparse
import csv
import itertools
import json
import signal
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", action="append", required=True,
                   help="base URL; repeat to spread requests round-robin across instances")
    p.add_argument("--path", default="/", help="request path, appended to each target")
    p.add_argument("--method", default="GET")
    body = p.add_mutually_exclusive_group()
    body.add_argument("--json", help="JSON body; sets Content-Type: application/json")
    body.add_argument("--data", help="raw body")
    p.add_argument("--header", action="append", default=[], help="'Name: value'; repeatable")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--duration", type=float, default=30, help="seconds to run (ignored if --requests is set)")
    p.add_argument("--requests", type=int, help="stop after this many requests in total")
    p.add_argument("--rate", type=float, help="max requests per second in total (default: as fast as possible)")
    p.add_argument("--timeout", type=float, default=5, help="per-request timeout in seconds")
    p.add_argument("--ok", default="200-299",
                   help="statuses that count as success, e.g. '200-299,409'")
    p.add_argument("--out", help="write every request to this CSV file")
    return p.parse_args()


def parse_ok(spec):
    ok = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            ok.update(range(int(lo), int(hi) + 1))
        elif part:
            ok.add(int(part))
    return ok


def fill(template, n):
    if template is None:
        return None
    return template.replace("{n}", str(n)).replace("{uuid}", str(uuid.uuid4()))


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[k]


def main():
    args = parse_args()
    ok_codes = parse_ok(args.ok)
    targets = [t.rstrip("/") for t in args.target]
    headers = []
    for h in args.header:
        name, _, value = h.partition(":")
        headers.append((name.strip(), value.strip()))
    if args.json is not None and not any(n.lower() == "content-type" for n, _ in headers):
        headers.append(("Content-Type", "application/json"))
    body_template = args.json if args.json is not None else args.data

    seq = itertools.count(1)
    seq_lock = threading.Lock()
    results = []  # (t_offset, target, status, latency_ms, error, instance)
    results_lock = threading.Lock()
    stop = threading.Event()
    start = time.monotonic()
    interval = args.concurrency / args.rate if args.rate else 0

    def on_signal(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    def worker():
        while not stop.is_set():
            with seq_lock:
                n = next(seq)
            if args.requests and n > args.requests:
                stop.set()
                break
            if not args.requests and time.monotonic() - start >= args.duration:
                stop.set()
                break
            target = targets[(n - 1) % len(targets)]
            url = target + fill(args.path, n)
            body = fill(body_template, n)
            req = urllib.request.Request(url, method=args.method.upper(),
                                         data=body.encode() if body is not None else None)
            for name, value in headers:
                req.add_header(name, fill(value, n))
            t0 = time.monotonic()
            status, error, instance = None, "", ""
            try:
                with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                    resp.read()
                    status = resp.status
                    instance = resp.headers.get("X-Instance", "") or ""
            except urllib.error.HTTPError as e:
                status = e.code
                instance = e.headers.get("X-Instance", "") if e.headers else ""
                e.read()
            except Exception as e:  # connection refused, reset, timeout, DNS
                error = type(e).__name__ + ": " + str(getattr(e, "reason", e))[:120]
            latency = (time.monotonic() - t0) * 1000
            with results_lock:
                results.append((t0 - start, target, status, latency, error, instance))
            if interval:
                time.sleep(max(0, interval - latency / 1000))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(args.concurrency)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop.set()
    for t in threads:
        t.join(timeout=args.timeout + 1)
    elapsed = time.monotonic() - start

    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_seconds", "target", "status", "latency_ms", "error", "instance"])
            for r in sorted(results):
                w.writerow([f"{r[0]:.3f}", r[1], r[2] if r[2] is not None else "", f"{r[3]:.1f}", r[4], r[5]])

    total = len(results)
    failed = [r for r in results if r[2] not in ok_codes]
    outcome = Counter(str(r[2]) if r[2] is not None else r[4].split(":")[0] for r in results)
    latencies = sorted(r[3] for r in results if r[2] is not None)
    per_target = defaultdict(lambda: [0, 0])
    for r in results:
        per_target[r[1]][0] += 1
        if r[2] not in ok_codes:
            per_target[r[1]][1] += 1
    timeline = defaultdict(Counter)
    for r in failed:
        timeline[int(r[0])][str(r[2]) if r[2] is not None else r[4].split(":")[0]] += 1

    print(f"requests: {total} in {elapsed:.1f}s ({total / elapsed if elapsed else 0:.1f}/s), "
          f"failed: {len(failed)} ({len(failed) / total * 100 if total else 0:.2f}%)")
    print("outcomes: " + ", ".join(f"{k}={v}" for k, v in outcome.most_common()))
    if latencies:
        print(f"latency ms: p50={percentile(latencies, 50):.0f} p95={percentile(latencies, 95):.0f} "
              f"p99={percentile(latencies, 99):.0f} max={latencies[-1]:.0f} "
              f"mean={statistics.mean(latencies):.0f}")
    if len(targets) > 1:
        for t, (n, f) in per_target.items():
            print(f"target {t}: {n} requests, {f} failed")
    instances = Counter(r[5] for r in results if r[5])
    if instances:
        print("served by (X-Instance): " + ", ".join(f"{k}={v}" for k, v in instances.most_common()))
    if timeline:
        print("failure timeline (second: outcomes):")
        for sec in sorted(timeline):
            print(f"  t+{sec:>4}s  " + ", ".join(f"{k}={v}" for k, v in timeline[sec].most_common()))
        errors = Counter(r[4] for r in failed if r[4])
        for e, c in errors.most_common(5):
            print(f"  error x{c}: {e}")

    summary = {
        "requests": total,
        "failed": len(failed),
        "elapsed_s": round(elapsed, 2),
        "outcomes": dict(outcome),
        "p95_ms": round(percentile(latencies, 95), 1) if latencies else None,
        "failure_seconds": sorted(timeline),
    }
    print("SUMMARY " + json.dumps(summary))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
