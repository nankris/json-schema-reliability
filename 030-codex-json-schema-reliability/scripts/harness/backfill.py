#!/usr/bin/env python3
"""Rewrite a runs.csv to the current FIELDS, filling token usage from the session rollout
when the exec stream had none (failed turns). Only for fresh (non-resumed) runs.
Usage: backfill.py EXP_DIR"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_one import FIELDS, find_rollout, rollout_stats, PRICE_IN, PRICE_CACHED, PRICE_OUT

p = os.path.join(sys.argv[1], "results", "runs.csv")
rows = list(csv.DictReader(open(p)))
for r in rows:
    if None in r:
        r["usage_src"] = r.pop(None)[0]
    if r.get("usage_src"):
        continue
    r["usage_src"] = "exec_stream"
    if "__chain__" in r.get("raw_jsonl", ""):
        continue
    if int(float(r["total_tokens"] or 0)) == 0 and r["thread_id"]:
        rs = rollout_stats(find_rollout(r["thread_id"]))
        ta = rs["_tot_after"]
        if ta:
            inp, cached, out = ta.get("input_tokens", 0), ta.get("cached_input_tokens", 0), ta.get("output_tokens", 0)
            r.update(input_tokens=inp, cached_input_tokens=cached, uncached_input_tokens=inp - cached,
                     output_tokens=out, reasoning_output_tokens=ta.get("reasoning_output_tokens", 0),
                     total_tokens=inp + out, cache_share=round(cached / inp, 4) if inp else "",
                     est_cost_usd=round(((inp - cached) * PRICE_IN + cached * PRICE_CACHED + out * PRICE_OUT) / 1e6, 5),
                     usage_src="rollout")
with open(p, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in FIELDS})
print("rows", len(rows))
