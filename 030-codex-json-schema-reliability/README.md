# #030 JSON reliability with and without a grammar (Codex `--output-schema`)

**Question.** When you ask Codex for structured data, does constrained decoding (`codex exec --output-schema schema.json`) give more valid JSON than just asking for JSON in the prompt? Measured as parse-valid and schema-valid rate on 50 extraction prompts.

**Short answer (this build, these prompts).**
- **Reliability:** if the prompt contains the JSON Schema, **plain prompting was already 100% parse-valid and 100% schema-valid (50/50)**, the same as `--output-schema`. The grammar added nothing measurable. A bare "reply in JSON with these keys" prompt (no types, no enums) was still 100% parse-valid but only **42% schema-valid** (21/50): free-text enums ("Volcanic eruption"), strings for nested objects ("Espoo, Finland"), and numbers as words ("just over two million").
- **Cost surprise:** `--output-schema` runs got **no prompt-cache hits** (cached input 0 in 48 of 50 runs, and 0 in 3 identical back-to-back repeats). Plain runs got ~12.2K cached tokens on every call. So the schema flag made each call about **4× more expensive** at list price: **$0.0303 vs $0.0077** per call (*estimates*).

## Setup

- Codex CLI `codex-cli 0.162.1`, model `gpt-6.1-sol`, default reasoning effort, ChatGPT Plus login. One headless call per prompt: `codex exec --json --skip-git-repo-check --sandbox read-only -C <empty temp dir> -o <final message file> [--output-schema <schema.json>] "<prompt>"`. `--output-schema` is the only structured-output flag in this build (`codex exec --help`).
- Data: 50 public texts, the plain-text intro sections of 50 English Wikipedia articles (CC BY-SA 4.0), fetched with the MediaWiki API on 2026-10-14 and capped at ~2,500 characters at a sentence boundary (mean 2,055 chars). 5 domains × 10 articles: people, cities, chemical elements, companies, historical events. Titles, URLs and revision ids are in `data/prompts.jsonl`. No private data.
- One strict JSON Schema per domain (`data/schemas/*.json`): all keys required, `additionalProperties: false`, nullable types, string arrays, one nested object (company HQ), enums (element category and state, event kind).
- Arms (50 calls each, one call per prompt, run 2 at a time):
  - `schema_flag`: prompt contains the schema **and** `--output-schema` is set (grammar-constrained).
  - `plain_json`: identical prompt, no flag. Prompt: "Extract structured data about the {domain} described in the text below. Use only the text; use null (or an empty list) when the text does not say. Do not run any commands or open any files; answer directly. Reply in JSON only: a single JSON object that matches this JSON Schema. {schema} TEXT: …"
  - `plain_keys` (added after the first two tied): same opening, but the format line is only "Reply in JSON with these keys: name, birth_year, …". No schema, types or enum values. This is the bare "reply in JSON" prompt most people write, so a schema failure here means the model guessed a different type/format than the schema wanted, not that it broke JSON.
- Metrics: **parse-valid** = the raw final message parses with `json.loads` (no fence stripping); **schema-valid** = it parses and validates against the domain schema (`jsonschema` Draft 2020-12). A lenient parse (strip code fences / take the outer `{…}`) is also recorded but was never needed.
- Consistency check (no ground truth): for 2–4 scalar fields per domain (e.g. birth year, atomic number, founding year, event kind), agreement of each plain arm's value with the `schema_flag` value (`results/field_agreement.csv`).
- Cost estimate: gpt-6.1-sol API list price $2.00/M uncached input, $0.10/M cached input, $10.00/M output (https://developers.openai.com/api/docs/models/gpt-6.1-sol, checked 2026-10-14). **Estimates only**; Plus is a flat subscription.

## Exact commands

```bash
source /workspace/tools/setup.sh; export PATH=/workspace/tools/mlenv/bin:$PATH   # python with jsonschema, pandas, matplotlib
python scripts/build_prompts.py                         # data/prompts.jsonl + data/schemas/*.json
python scripts/run_json.py schema_flag P01              # one call
scripts/driver.sh 2                                     # schema_flag + plain_json, all 50 (scripts/jobs.txt)
JOBS=jobs_plain_keys.txt scripts/driver.sh 2            # plain_keys arm
for k in 1 2 3; do python scripts/run_json.py probe_schema_r$k P21; done   # cache probe: same schema prompt 3x in a row
python scripts/analyze.py
```

## Results (153 calls, 2026-10-14 19:42–19:59 UTC / 2026-10-15 01:12–01:29 IST)

| Arm | Calls | Parse-valid | Schema-valid | Input tokens | Cached input | Calls with any cache hit | Output tokens | Wall | Est. cost / call | Est. cost, 50 calls |
|---|---|---|---|---|---|---|---|---|---|---|
| `--output-schema` (+ schema in prompt) | 50 | 100% | **100%** | 15,233 | 497 | 2/50 | 80.6 | 8.5 s | **$0.0303** | $1.52 |
| plain, schema in prompt | 50 | 100% | **100%** | 15,011 | 12,186 | 50/50 | 80.4 | 8.5 s | $0.0077 | $0.38 |
| plain, key names only | 50 | 100% | **42%** | 14,670 | 12,288 | 50/50 | 95.4 | 6.4 s | $0.0070 | $0.35 |

Cache probe (`probe_schema_r1..r3`, the Helium prompt with `--output-schema`, run back to back): cached input **0, 0, 0** of ~15.0K each.

Schema-valid by domain:

| Domain | `--output-schema` | plain, schema in prompt | plain, keys only | Typical keys-only failure |
|---|---|---|---|---|
| person | 10/10 | 10/10 | 9/10 | nationality as a list |
| city | 10/10 | 10/10 | 8/10 | population as words ("more than 9.8 million") |
| element | 10/10 | 10/10 | 2/10 | state left null; category "metal" not in enum |
| company | 10/10 | 10/10 | 0/10 | headquarters as one string, not `{city, country}` |
| event | 10/10 | 10/10 | 2/10 | free-text kind ("Peace treaty", "Volcanic eruption") |

Scalar-field agreement with the `--output-schema` answer: plain + schema 138/140 (98.6%), keys only 121/140 (86.4%).

Chart: `results/chart.png` (valid rates, input-token mix, est. cost per call).

### What the numbers say
1. **With the schema in the prompt, the grammar was redundant.** Every plain reply was bare JSON (no code fences, no prose) and matched the schema, including enums, nullable fields and the nested object.
2. **What you put in the prompt matters far more than the flag.** Dropping the schema from the prompt kept the JSON parseable but cut schema validity from 100% to 42%. The model's own choices (a string for HQ, "Volcanic eruption" for kind) are reasonable. They just aren't the schema's.
3. **The grammar can push a guess.** For Vienna ("just over two million") `--output-schema` wrote `population: 2000000`, while the plain arm with the same schema wrote `null`. That's one case, but it's the known risk of forcing a type.
4. **`--output-schema` disabled prompt caching here.** Codex's ~12K-token fixed prefix was a cache hit on 100/100 plain calls and on 2/53 schema calls. That makes the flag ~4× more expensive per call at list price, which matters if you run many small structured calls. I can't tell from the client side whether Codex or the API causes the miss.

## Caveats
- One model, one Codex build, one call per prompt (no repeats except the 3-call probe). 50 prompts can't show failure rates much below ~2%.
- Texts are short, clean Wikipedia intros. Messier inputs or much larger schemas might break plain prompting where the grammar wouldn't.
- No ground-truth labels. The agreement figures only show consistency with the `--output-schema` answers, not correctness.
- The keys-only arm is deliberately under-specified. Its schema failures measure the gap between the model's defaults and this schema, not JSON breakage.
- A sandbox VM restart at ~19:48 UTC killed the first driver mid-batch. It was restarted and resumed from `runs.csv`. A few calls finished just before the restart lost their rows and were re-run (raw files overwritten), so each prompt has exactly one row per arm.
- #014 ran on the same account during the first ~5 minutes; rate-limit percentages include it.

## Files
- `scripts/build_prompts.py` (fetch + schemas), `scripts/run_json.py` (one call + grading), `scripts/driver.sh`, `scripts/jobs.txt`, `scripts/jobs_plain_keys.txt`, `scripts/analyze.py`
- `data/prompts.jsonl` (50 texts with source URL and revision id), `data/schemas/*.json`
- `results/runs.csv` (one row per call, incl. 3 probe rows), `results/summary.csv`, `results/per_domain.csv`, `results/failures.csv`, `results/field_agreement.csv`, `results/driver.log`
- `results/raw/<arm>__<id>.jsonl` (raw `codex exec --json` stream), `.txt` (final message), `.stderr`
