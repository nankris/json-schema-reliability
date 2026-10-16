#!/usr/bin/env python3
"""#030 summary + chart. results/runs.csv -> results/summary.csv, results/per_domain.csv, results/field_agreement.csv, results/chart.png"""
import json, os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_csv(os.path.join(HERE, "results", "runs.csv"))
order = [a for a in ["schema_flag", "plain_json", "plain_keys"] if a in set(df.arm)]
df = df[df.arm.isin(order)]
lab = {"schema_flag": "--output-schema\n(+ schema in prompt)", "plain_json": "plain prompt\n(schema in prompt)", "plain_keys": "plain prompt\n(key names only)"}
g = df.groupby("arm")
s = pd.DataFrame({"runs": g.size(), "parse_valid_rate": g.parse_valid.mean(), "lenient_parse_valid_rate": g.lenient_parse_valid.mean(),
    "schema_valid_rate": g.strict_schema_valid.mean(), "schema_valid_after_lenient_parse": g.schema_valid_lenient.mean(),
    "input_tokens_mean": g.input_tokens.mean().round(0), "cached_input_mean": g.cached_input_tokens.mean().round(0),
    "runs_with_cache_hit": g.cached_input_tokens.apply(lambda x: int((x > 0).sum())),
    "output_tokens_mean": g.output_tokens.mean().round(1), "wall_s_mean": g.wall_s.mean().round(2),
    "est_cost_mean_usd": g.est_cost_usd.mean().round(5), "est_cost_total_usd": g.est_cost_usd.sum().round(4),
    "tool_items": g.tool_items.sum(), "retries": g.retries.sum()}).reindex(order)
s.to_csv(os.path.join(HERE, "results", "summary.csv")); print(s.T.to_string())
pdm = df.pivot_table(index="domain", columns="arm", values="strict_schema_valid", aggfunc="mean").reindex(columns=order)
pdm.to_csv(os.path.join(HERE, "results", "per_domain.csv")); print(pdm.to_string())
fails = df[df.strict_schema_valid == 0][["arm", "id", "domain", "title", "error"]]
fails.to_csv(os.path.join(HERE, "results", "failures.csv"), index=False); print(fails.to_string())
# agreement of scalar fields with the schema_flag answer (a consistency check, not ground truth)
SCAL = {"person": ["birth_year", "death_year"], "city": ["country", "is_capital", "population"], "element": ["symbol", "atomic_number", "category", "state_at_room_temperature"],
        "company": ["founded_year", "is_public"], "event": ["start_year", "end_year", "kind"]}
def load(arm, pid):
    try: return json.loads(open(os.path.join(HERE, "results", "raw", f"{arm}__{pid}.txt")).read())
    except Exception: return None
rows = []
for pid, dom in df[["id", "domain"]].drop_duplicates().values:
    ref = load("schema_flag", pid)
    for arm in order[1:]:
        o = load(arm, pid)
        for f in SCAL[dom]:
            a = ref.get(f) if isinstance(ref, dict) else None; b = o.get(f) if isinstance(o, dict) else None
            norm = lambda v: v.strip().lower() if isinstance(v, str) else v
            rows.append(dict(arm=arm, id=pid, domain=dom, field=f, schema_flag=a, other=b, agree=int(norm(a) == norm(b))))
ag = pd.DataFrame(rows); ag.to_csv(os.path.join(HERE, "results", "field_agreement.csv"), index=False)
print(ag.groupby("arm").agree.mean().round(3)); print(ag[ag.agree == 0].to_string())
fig, ax = plt.subplots(1, 3, figsize=(16, 4.8)); x = range(len(order)); c = ["#55a868", "#4c72b0", "#dd8452"][:len(order)]
w = 0.38
ax[0].bar([i - w / 2 for i in x], s.parse_valid_rate * 100, w, color=c, alpha=0.9, label="parse-valid (raw reply is JSON)")
ax[0].bar([i + w / 2 for i in x], s.schema_valid_rate * 100, w, color=c, alpha=0.45, hatch="//", label="schema-valid")
for i, a in enumerate(order):
    ax[0].text(i - w / 2, s.parse_valid_rate[a] * 100 + 1, f"{s.parse_valid_rate[a]:.0%}", ha="center", fontsize=9)
    ax[0].text(i + w / 2, s.schema_valid_rate[a] * 100 + 1, f"{s.schema_valid_rate[a]:.0%}", ha="center", fontsize=9)
ax[0].set_ylim(0, 128); ax[0].set_title("Valid replies (50 prompts per arm)\nsolid = parses as JSON, hatched = matches schema", fontsize=10); ax[0].legend(fontsize=7.5, loc="upper center", ncol=2)
ax[1].bar(x, s.cached_input_mean / 1000, color="#8fbcd4", label="cached input")
ax[1].bar(x, (s.input_tokens_mean - s.cached_input_mean) / 1000, bottom=s.cached_input_mean / 1000, color="#e3a07a", label="uncached input")
ax[1].set_title("Input tokens per call (K), mean", fontsize=10); ax[1].legend(fontsize=8, loc="lower right")
ax[2].bar(x, s.est_cost_mean_usd * 100, color=c)
for i, a in enumerate(order): ax[2].text(i, s.est_cost_mean_usd[a] * 100 * 1.02, f"{s.est_cost_mean_usd[a]*100:.2f}¢", ha="center", fontsize=9)
ax[2].set_title("Est. API cost per call (US cents)", fontsize=10); ax[2].set_ylim(0, s.est_cost_mean_usd.max() * 100 * 1.15)
for a_ in ax: a_.set_xticks(list(x)); a_.set_xticklabels([lab[o] for o in order], fontsize=8.5); a_.grid(axis="y", alpha=0.3)
fig.suptitle("Codex 0.162.1 (gpt-6.1-sol): JSON extraction from 50 Wikipedia intros, with and without --output-schema", fontsize=11)
fig.tight_layout(); fig.savefig(os.path.join(HERE, "results", "chart.png"), dpi=130); print("wrote chart")
