#!/usr/bin/env python3
"""Run one headless Codex task on a fresh copy of a fixture and record metrics.

Usage:
  run_one.py --exp DIR --cond LABEL --task PATH --rep N [--cfg k=v ...] [--timeout S]
             [--check "node test.js"] [--prompt TEXT] [--workdir DIR] [--resume THREAD_ID]
             [--no-copy]

Writes:
  DIR/results/raw/<cond>__<task>__r<rep>.jsonl   raw `codex exec --json` event stream
  DIR/results/raw/<cond>__<task>__r<rep>.stderr  stderr (MCP noise filtered out)
  DIR/results/runs.csv                           one summary row per run (appended)
Exits 3 and touches _harness/QUOTA_HIT if Codex reports a usage/rate limit.
"""
import argparse, csv, fcntl, glob, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time

HARNESS = os.path.dirname(os.path.abspath(__file__))
QUOTA_FLAG = os.path.join(HARNESS, "QUOTA_HIT")
SESS_ROOT = os.path.expanduser("~/.codex/sessions")
# gpt-6.1-sol public API list price, USD per 1M tokens (standard, short context), checked 2026-10-14
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
PRICE_IN, PRICE_CACHED, PRICE_OUT = 2.00, 0.10, 10.00
LIMIT_RE = re.compile(r"usage limit|rate limit|rate_limit|too many requests|429|quota|limit reached|hit your", re.I)
FIELDS = ["exp", "cond", "task", "rep", "start_epoch", "wall_s", "exit_code", "timed_out", "passed",
          "subtests_passed", "subtests_total", "test_js_untouched", "input_tokens", "cached_input_tokens",
          "uncached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens", "cache_share",
          "est_cost_usd", "model_calls", "tool_calls", "compactions", "peak_context_tokens", "model",
          "effort", "limit_error", "retries", "rl_primary_used_pct", "rl_secondary_used_pct", "thread_id", "cfg", "raw_jsonl", "usage_src"]


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_hashes(root):
    return {p: sha(p) for p in glob.glob(os.path.join(root, "**", "test.js"), recursive=True)}


def find_rollout(thread_id):
    hits = glob.glob(os.path.join(SESS_ROOT, "**", f"*{thread_id}*.jsonl"), recursive=True)
    return max(hits, key=os.path.getmtime) if hits else None


def rollout_stats(path, since_line=0):
    s = dict(model_calls=0, tool_calls=0, compactions=0, peak_context_tokens=0, model="", effort="",
             rl_primary_used_pct="", rl_secondary_used_pct="", _tot_before=None, _tot_after=None)
    if not path:
        return s
    with open(path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if i < since_line:
            if '"token_count"' in line:
                try:
                    tu = ((json.loads(line).get("payload") or {}).get("info") or {}).get("total_token_usage")
                    if tu:
                        s["_tot_before"] = tu
                except Exception:
                    pass
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t, p = d.get("type"), d.get("payload") or {}
        if not isinstance(p, dict):
            continue
        pt = p.get("type")
        if t == "turn_context":
            s["model"] = p.get("model", s["model"])
            cm = (p.get("collaboration_mode") or {}).get("settings") or {}
            s["effort"] = p.get("effort") or cm.get("reasoning_effort") or "default"
        if t == "compacted" or pt in ("context_compacted", "compaction") or "compact" in str(pt or ""):
            s["compactions"] += 1
        if pt in ("custom_tool_call", "function_call", "local_shell_call"):
            s["tool_calls"] += 1
        if pt == "token_count":
            info = p.get("info") or {}
            last = info.get("last_token_usage") or {}
            if info.get("total_token_usage"):
                s["_tot_after"] = info["total_token_usage"]
            if last:
                s["model_calls"] += 1
                s["peak_context_tokens"] = max(s["peak_context_tokens"], last.get("input_tokens", 0))
            rl = p.get("rate_limits") or {}
            if rl.get("primary"):
                s["rl_primary_used_pct"] = rl["primary"].get("used_percent", "")
            if rl.get("secondary"):
                s["rl_secondary_used_pct"] = rl["secondary"].get("used_percent", "")
    return s


def subtests(root):
    """For a suite dir, run each sub-package's test.js; for a single fixture, run test.js."""
    subs = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "test.js")))
    if not subs:
        return None
    ok = 0
    for d in subs:
        r = subprocess.run(["node", "test.js"], cwd=os.path.join(root, d), capture_output=True, timeout=60)
        ok += r.returncode == 0
    return ok, len(subs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True)
    ap.add_argument("--cond", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--cfg", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--check", default="node test.js")
    ap.add_argument("--prompt", default="Make `node test.js` pass by fixing the code. Do not edit test.js.")
    ap.add_argument("--workdir", default=None, help="reuse this dir instead of a fresh temp copy")
    ap.add_argument("--resume", default=None, help="thread id to resume with `codex exec resume`")
    ap.add_argument("--tag", default="", help="extra label for the raw file name")
    a = ap.parse_args()

    if os.path.exists(QUOTA_FLAG):
        print("QUOTA_HIT flag present; not running", file=sys.stderr)
        sys.exit(3)
    raw_dir = os.path.join(a.exp, "results", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    task_name = os.path.basename(a.task.rstrip("/"))
    stem = f"{a.cond}__{task_name}{('__' + a.tag) if a.tag else ''}__r{a.rep}"
    raw_path = os.path.join(raw_dir, stem + ".jsonl")

    csv_path = os.path.join(a.exp, "results", "runs.csv")
    if os.path.exists(csv_path) and not a.resume:
        for r in csv.DictReader(open(csv_path)):
            if r["cond"] == a.cond and r["task"] == task_name and str(r["rep"]) == str(a.rep):
                print(f"skip {stem}: already in runs.csv")
                return
    if a.workdir:
        work = a.workdir
        if not os.path.exists(work):
            shutil.copytree(a.task, work)
    else:
        work = tempfile.mkdtemp(prefix="tig_")
        shutil.copytree(a.task, work, dirs_exist_ok=True)
    before = test_hashes(work)

    cmd = ["codex", "exec"]
    if a.resume:
        cmd += ["resume"]
    cmd += ["--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox"]
    for c in a.cfg:
        cmd += ["-c", c]
    if a.resume:
        cmd += [a.resume, a.prompt]
    else:
        cmd += ["-C", work, a.prompt]

    rollout_before = None
    since = 0
    if a.resume:
        rollout_before = find_rollout(a.resume)
        since = sum(1 for _ in open(rollout_before)) if rollout_before else 0

    t0 = time.time()
    start_utc = int(t0)  # unix epoch seconds
    timed_out = False
    with open(raw_path, "w") as out, open(raw_path.replace(".jsonl", ".stderr"), "w") as err:
        try:
            p = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                               cwd=work, timeout=a.timeout, text=True)
            rc = p.returncode
            err.write("\n".join(l for l in p.stderr.splitlines() if "rmcp" not in l and "Reading additional" not in l))
        except subprocess.TimeoutExpired as e:
            rc, timed_out = -9, True
            err.write("TIMEOUT\n")
    wall = time.time() - t0

    usage = dict(input_tokens=0, cached_input_tokens=0, output_tokens=0, reasoning_output_tokens=0)
    thread_id, limit_err, errors, retries, completed = a.resume or "", "", [], 0, False
    for line in open(raw_path):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id", thread_id)
        if ev.get("type") == "turn.completed":
            completed = True
            for k in usage:
                usage[k] += (ev.get("usage") or {}).get(k, 0) or 0
        msg = ""
        if ev.get("type") in ("turn.failed", "error"):
            msg = json.dumps(ev)
        it = ev.get("item") or {}
        if it.get("type") == "error":
            msg = it.get("message", "")
            if "Under-development features" in msg:
                msg = ""
        if msg:
            errors.append(msg[:300])
            if "Reconnecting" in msg:
                retries += 1  # transient 429/stream retry; Codex retried on its own
            elif LIMIT_RE.search(msg):
                limit_err = msg[:300]
    if not completed and not limit_err:
        for m in errors:
            if "Reconnecting" not in m and LIMIT_RE.search(m):
                limit_err = m[:300]
    if not limit_err and not completed:
        e = open(raw_path.replace(".jsonl", ".stderr")).read()
        m = LIMIT_RE.search(e)
        if m and ("usage" in e.lower() or "rate" in e.lower()):
            limit_err = e[max(0, m.start() - 100): m.start() + 200].replace("\n", " ")

    rs = rollout_stats(find_rollout(thread_id) if thread_id else None, since)
    # Token usage: prefer the session rollout's cumulative counter (delta for resumed turns),
    # because a failed turn (e.g. budget exhausted) emits no usage in the exec stream.
    tb, ta = rs.pop("_tot_before"), rs.pop("_tot_after")
    usage_src = "exec_stream"
    if ta:
        tb = tb or {}
        for k in usage:
            usage[k] = (ta.get(k, 0) or 0) - (tb.get(k, 0) or 0)
        usage_src = "rollout"
    rs["usage_src"] = usage_src
    chk = subprocess.run(a.check, shell=True, cwd=work, capture_output=True, timeout=120)
    passed = chk.returncode == 0
    st = subtests(work)
    after = test_hashes(work)
    untouched = before == after

    inp, cached, outp = usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]
    cost = ((inp - cached) * PRICE_IN + cached * PRICE_CACHED + outp * PRICE_OUT) / 1e6
    row = dict(exp=os.path.basename(a.exp.rstrip("/")), cond=a.cond, task=task_name, rep=a.rep,
               start_epoch=start_utc, wall_s=round(wall, 1), exit_code=rc, timed_out=timed_out,
               passed=int(passed and untouched), subtests_passed=st[0] if st else "",
               subtests_total=st[1] if st else "", test_js_untouched=int(untouched),
               input_tokens=inp, cached_input_tokens=cached, uncached_input_tokens=inp - cached,
               output_tokens=outp, reasoning_output_tokens=usage["reasoning_output_tokens"],
               total_tokens=inp + outp, cache_share=round(cached / inp, 4) if inp else "",
               est_cost_usd=round(cost, 5), limit_error=limit_err, retries=retries, thread_id=thread_id,
               cfg=" ".join(a.cfg), raw_jsonl=os.path.relpath(raw_path, a.exp), **rs)
    with open(csv_path, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        new = f.tell() == 0
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
        fcntl.flock(f, fcntl.LOCK_UN)
    print(json.dumps({k: row[k] for k in ("cond", "task", "rep", "passed", "subtests_passed", "total_tokens",
                                          "cached_input_tokens", "est_cost_usd", "model_calls", "compactions",
                                          "wall_s", "limit_error", "retries", "rl_primary_used_pct")}))
    if errors and not limit_err:
        print("errors:", errors[:3], file=sys.stderr)
    if limit_err:
        open(QUOTA_FLAG, "w").write(str(int(time.time())) + " " + limit_err + "\n")
        sys.exit(3)
    if not a.workdir:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
