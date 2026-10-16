#!/bin/bash
# driver.sh JOBS_FILE PARALLEL LOG : each line of JOBS_FILE = arguments to run_one.py
source /workspace/tools/setup.sh
export H=/workspace/work/tig/_harness
JOBS=$1; P=${2:-3}; LOG=${3:-$JOBS.log}
echo "start $(date -u +%s) jobs=$(grep -vc '^#' $JOBS) P=$P" >> $LOG
grep -v '^#' "$JOBS" | grep -v '^$' | xargs -d '\n' -P "$P" -n 1 bash -c '[ -e "$H/QUOTA_HIT" ] && exit 0; eval "python3 $H/run_one.py $1"' _ >> $LOG 2>&1
echo "done $(date -u +%s)" >> $LOG
