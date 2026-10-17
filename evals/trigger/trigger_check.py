"""Trigger check: does Claude load the `qa` skill within its first few steps?

Usage: python3 trigger_check.py queries.json <sample-repo-dir> out.json [runs]
Install the skill under test as ~/.claude/skills/qa first. Set QA_TRIGGER_MODEL to pin a model.
skill-creator's run_eval tests a temporary command file, which Claude Code did not invoke as a skill
in our runs, so this script tests the installed skill instead.

Runs `claude -p` per query in a sample repo with read-only tools allowed and risky ones denied,
watches the stream, and records whether Skill(qa) is called before MAX_TOOLS tool calls.
"""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

queries_file, cwd, out_file = sys.argv[1], sys.argv[2], sys.argv[3]
runs = int(sys.argv[4]) if len(sys.argv) > 4 else 1
MODEL = os.environ.get("QA_TRIGGER_MODEL")
MAX_TOOLS, TIMEOUT = 8, 150
ALLOW = "Read Glob Grep Skill Bash(ls:*) Bash(find:*) Bash(cat:*) Bash(head:*) Bash(pwd) Bash(git status:*) Bash(git log:*) Bash(tree:*)"
DENY = ("Write Edit NotebookEdit Bash(docker:*) Bash(kubectl:*) Bash(rm:*) Bash(curl:*) Bash(python3:*) Bash(python:*) "
        "Bash(make:*) Bash(npm:*) Bash(pip:*) Bash(git push:*) Bash(git commit:*) Bash(helm:*) Bash(terraform:*) Bash(tofu:*) Agent")

def one(q):
    cmd = ["claude", "-p", q] + (["--model", MODEL] if MODEL else []) + ["--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--allowedTools", ALLOW, "--disallowedTools", DENY]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    tools, cur, buf, start, hit = [], None, "", time.time(), False
    try:
        for line in p.stdout:
            if time.time() - start > TIMEOUT:
                break
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "stream_event":
                if e.get("type") == "result":
                    break
                continue
            se = e["event"]
            if se.get("type") == "content_block_start" and se.get("content_block", {}).get("type") == "tool_use":
                cur, buf = se["content_block"]["name"], ""
            elif se.get("type") == "content_block_delta" and cur and se.get("delta", {}).get("type") == "input_json_delta":
                buf += se["delta"].get("partial_json", "")
            elif se.get("type") == "content_block_stop" and cur:
                try:
                    inp = json.loads(buf or "{}")
                except ValueError:
                    inp = {}
                label = cur + (":" + str(inp.get("skill")) if cur == "Skill" else "")
                tools.append(label)
                if cur == "Skill" and str(inp.get("skill", "")).split(":")[-1] == "qa":
                    hit = True
                    break
                cur = None
                if len(tools) >= MAX_TOOLS:
                    break
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
    return {"triggered": hit, "tools": tools, "seconds": round(time.time() - start, 1)}

qs = json.load(open(queries_file))
jobs = [(i, r) for i in range(len(qs)) for r in range(runs)]
with ThreadPoolExecutor(5) as ex:
    res = list(ex.map(lambda j: (j[0], one(qs[j[0]]["query"])), jobs))
out = []
for i, q in enumerate(qs):
    rs = [r for k, r in res if k == i]
    n = sum(r["triggered"] for r in rs)
    ok = (n / len(rs) >= 0.5) == q["should_trigger"]
    out.append({**q, "trigger_rate": f"{n}/{len(rs)}", "pass": ok, "tools": [r["tools"] for r in rs]})
    print(f"{'PASS' if ok else 'FAIL'} {n}/{len(rs)} expected={q['should_trigger']} first={rs[0]['tools'][:4]} :: {q['query'][:60]}", flush=True)
tp = sum(o["pass"] and o["should_trigger"] for o in out); tn = sum(o["pass"] and not o["should_trigger"] for o in out)
print(f"SCORE {tp+tn}/{len(out)} recall={tp}/{sum(o['should_trigger'] for o in out)} specificity={tn}/{sum(not o['should_trigger'] for o in out)}")
json.dump(out, open(out_file, "w"), ensure_ascii=False, indent=2)
