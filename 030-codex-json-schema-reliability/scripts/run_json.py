#!/usr/bin/env python3
"""One extraction call through headless Codex, with or without --output-schema.
Usage: run_json.py ARM PROMPT_ID   (ARM = schema_flag | plain_json | plain_keys)
Raw stream -> results/raw/<arm>__<id>.jsonl, final message -> results/raw/<arm>__<id>.txt,
one row appended to results/runs.csv. Exit 3 + _harness/QUOTA_HIT on a usage limit."""
import csv, fcntl, json, os, re, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = "/workspace/work/tig/_harness"
sys.path.insert(0, os.path.join(HERE, "scripts", "harness"))  # copy of the shared harness (run_one.py helpers)
from run_one import rollout_stats, find_rollout, LIMIT_RE, QUOTA_FLAG, PRICE_IN, PRICE_CACHED, PRICE_OUT
import jsonschema

arm, pid = sys.argv[1], sys.argv[2]
if os.path.exists(QUOTA_FLAG):
    sys.exit(3)
P = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(HERE, "data", "prompts.jsonl"))}[pid]
schema_path = os.path.join(HERE, "data", "schemas", P["domain"] + ".json")
schema = json.load(open(schema_path))
csv_path = os.path.join(HERE, "results", "runs.csv")
if os.path.exists(csv_path) and any(r["arm"] == arm and r["id"] == pid for r in csv.DictReader(open(csv_path))):
    print("skip", arm, pid); sys.exit(0)
head = (f"Extract structured data about the {P['domain']} described in the text below. Use only the text; "
        "use null (or an empty list) when the text does not say. Do not run any commands or open any files; answer directly.\n\n")
if arm == "plain_keys":  # the bare "reply in JSON" prompt: key names only, no schema, no types, no enums
    fmt = "Reply in JSON with these keys: " + ", ".join(schema["required"]) + ".\n\n"
else:                    # schema_flag and plain_json: the full JSON Schema in the prompt
    fmt = f"Reply in JSON only: a single JSON object that matches this JSON Schema.\n{json.dumps(schema)}\n\n"
prompt = head + fmt + f"TEXT:\n{P['text']}\n"
stem = os.path.join(HERE, "results", "raw", f"{arm}__{pid}")
work = tempfile.mkdtemp(prefix="tigjson_")
cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "-C", work, "-o", stem + ".txt"]
if arm == "schema_flag" or arm.startswith("probe_schema"):
    cmd += ["--output-schema", schema_path]
cmd += [prompt]
t0 = time.time()
with open(stem + ".jsonl", "w") as out:
    try:
        p = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, timeout=240)
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        rc, err = -9, "TIMEOUT"
wall = time.time() - t0
open(stem + ".stderr", "w").write("\n".join(l for l in err.splitlines() if "rmcp" not in l and "Reading additional" not in l))
usage = dict(input_tokens=0, cached_input_tokens=0, output_tokens=0)
tid, limit_err, msgs, tools, retries = "", "", [], 0, 0
for line in open(stem + ".jsonl"):
    try: ev = json.loads(line)
    except Exception: continue
    if ev.get("type") == "thread.started": tid = ev.get("thread_id", "")
    if ev.get("type") == "turn.completed":
        for k in usage: usage[k] += (ev.get("usage") or {}).get(k, 0) or 0
    it = ev.get("item") or {}
    if ev.get("type") == "item.completed" and it.get("type") == "agent_message": msgs.append(it.get("text", ""))
    if ev.get("type") == "item.completed" and it.get("type") in ("command_execution", "mcp_tool_call", "file_change"): tools += 1
    m = it.get("message", "") if it.get("type") == "error" else (json.dumps(ev) if ev.get("type") in ("turn.failed", "error") else "")
    if m and "Under-development" not in m:
        if "Reconnecting" in m: retries += 1
        elif LIMIT_RE.search(m): limit_err = m[:300]
final = open(stem + ".txt").read() if os.path.exists(stem + ".txt") else (msgs[-1] if msgs else "")
parse_ok = lenient_ok = schema_ok = 0; err_kind = ""
obj = None
try:
    obj = json.loads(final); parse_ok = 1
except Exception as e:
    err_kind = "parse"
    m = re.search(r"```(?:json)?\s*(.*?)```", final, re.S)
    cand = m.group(1) if m else final[final.find("{"): final.rfind("}") + 1]
    try: obj = json.loads(cand)
    except Exception: obj = None
lenient_ok = int(obj is not None)
if obj is not None:
    try:
        jsonschema.Draft202012Validator(schema).validate(obj); schema_ok = 1
    except jsonschema.ValidationError as e:
        err_kind = (err_kind + ";" if err_kind else "") + "schema:" + e.message[:120]
rs = rollout_stats(find_rollout(tid) if tid else None)
inp, cached, outp = usage["input_tokens"], usage["cached_input_tokens"], usage["output_tokens"]
row = dict(arm=arm, id=pid, domain=P["domain"], title=P["title"], start_epoch=int(t0), wall_s=round(wall, 1), exit_code=rc,
           final_chars=len(final), parse_valid=parse_ok, lenient_parse_valid=lenient_ok, schema_valid=schema_ok,
           schema_valid_lenient=schema_ok if lenient_ok else 0, strict_schema_valid=int(parse_ok and schema_ok), error=err_kind,
           tool_items=tools, input_tokens=inp, cached_input_tokens=cached, output_tokens=outp,
           est_cost_usd=round(((inp - cached) * PRICE_IN + cached * PRICE_CACHED + outp * PRICE_OUT) / 1e6, 5),
           model_calls=rs["model_calls"], model=rs["model"], rl_primary_used_pct=rs["rl_primary_used_pct"],
           limit_error=limit_err, retries=retries, thread_id=tid)
with open(csv_path, "a", newline="") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    w = csv.DictWriter(f, fieldnames=list(row)); 
    if f.tell() == 0: w.writeheader()
    w.writerow(row); fcntl.flock(f, fcntl.LOCK_UN)
print(json.dumps({k: row[k] for k in ("arm", "id", "parse_valid", "schema_valid", "strict_schema_valid", "error", "input_tokens", "output_tokens", "wall_s", "rl_primary_used_pct", "limit_error")}))
if limit_err:
    open(QUOTA_FLAG, "w").write(f"{int(time.time())} {limit_err}\n"); sys.exit(3)
