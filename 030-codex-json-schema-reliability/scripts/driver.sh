#!/bin/bash
# driver.sh [P] : run every line of scripts/jobs.txt (ARM ID) through run_json.py, P at a time
source /workspace/tools/setup.sh; export PATH=/workspace/tools/mlenv/bin:$PATH
E=/workspace/work/tig/030-codex-json-schema-reliability; H=/workspace/work/tig/_harness
echo "start $(date -u +%s)" >> $E/results/driver.log
xargs -P ${1:-2} -L 1 bash -c '[ -e '$H'/QUOTA_HIT ] && exit 0; python '$E'/scripts/run_json.py "$0" "$1"' < $E/scripts/${JOBS:-jobs.txt} >> $E/results/driver.log 2>&1
echo "done $(date -u +%s)" >> $E/results/driver.log
