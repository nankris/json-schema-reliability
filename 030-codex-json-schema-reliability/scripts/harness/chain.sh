#!/bin/bash
# chain.sh EXP COND REP [extra -c cfg ...]
# One long Codex session: fix the 14 SUITE14 packages one per turn, resuming the same thread
# with `codex exec resume <thread_id>`. Each turn is a row in EXP/results/runs.csv (task=<pkg>,
# tag=chain). With FRESH=1 every package gets its own fresh `codex exec` (no resume) in the same dir. Final check `node run_all.js` is recorded as task=CHAIN_TOTAL by summarize step.
source /workspace/tools/setup.sh
H=/workspace/work/tig/_harness
EXP=$1; COND=$2; REP=$3; shift 3
CFG=()
for c in "$@"; do CFG+=(--cfg "$c"); done
WORK=$(mktemp -d /tmp/tigchain_XXXX)
rm -rf "$WORK"; cp -r $H/fixtures/SUITE14 "$WORK"
TID=""
for pkg in $(ls $H/fixtures/SUITE14 | grep -v run_all.js | sort); do
  [ -e $H/QUOTA_HIT ] && { echo "quota flag, stopping chain"; break; }
  PROMPT="Make \`node test.js\` pass inside the package folder \`$pkg/\` by fixing that package's code. Do not edit any test.js. Only work on $pkg/ in this turn."
  if [ -z "$TID" ] || [ "${FRESH:-0}" = 1 ]; then
    python3 $H/run_one.py --exp "$EXP" --cond "$COND" --task "$H/fixtures/SUITE14/$pkg" --rep "$REP" --tag chain \
      --workdir "$WORK" --check "cd $pkg && node test.js" --prompt "$PROMPT" --timeout 600 "${CFG[@]}"
    [ "${FRESH:-0}" = 1 ] || TID=$(python3 -c "import csv,sys; rows=list(csv.DictReader(open(sys.argv[1]))); print([r for r in rows if r['cond']==sys.argv[2] and str(r['rep'])==sys.argv[3]][-1]['thread_id'])" "$EXP/results/runs.csv" "$COND" "$REP")
    if [ "${FRESH:-0}" != 1 ]; then echo "chain $COND r$REP thread=$TID"; [ -z "$TID" ] && { echo "no thread id, aborting chain"; break; }; fi
  else
    python3 $H/run_one.py --exp "$EXP" --cond "$COND" --task "$H/fixtures/SUITE14/$pkg" --rep "$REP" --tag chain \
      --workdir "$WORK" --resume "$TID" --check "cd $pkg && node test.js" --prompt "$PROMPT" --timeout 600 "${CFG[@]}"
  fi
  rc=$?
  if [ -n "$TID" ]; then
    NEW=$(head -n 1 "$EXP/results/raw/${COND}__${pkg}__chain__r${REP}.jsonl" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('thread_id',''))" 2>/dev/null)
    [ -n "$NEW" ] && [ "$NEW" != "$TID" ] && { echo "resume started a different thread ($NEW != $TID), aborting chain"; break; }
  fi
  [ $rc -eq 3 ] && { echo "quota hit during chain"; break; }
done
cd "$WORK" && node run_all.js > /dev/null 2>&1; echo "CHAIN_DONE exp=$EXP cond=$COND rep=$REP thread=$TID all_pass_rc=$? $(node run_all.js 2>/dev/null | grep SUMMARY)"
rm -rf "$WORK"
