#!/usr/bin/env bash
# Verify an adoption of fix 17 in a scratch export (the project scheduler is not touched).
# Usage: rb17_verify.sh CFG      CFG in {a, b, c, ab, abc}
# Adopted code, seeds 0-9 of the full grid, R-BurstHADS, must equal variant f17<CFG> row for row.
set -u
CFG="$1"
S="/c/Users/Shrike/AppData/Local/Temp/claude/C--my-folder-projects-Improvement-on-Burst-HADS--claude-worktrees-claude-md-review-status-325adb/eb9e3acb-8c59-4ea0-9e21-35fc4839a80b/scratchpad"
P="/c/my folder/projects/Improvement on Burst HADS"
X="$S/rb17_$CFG"
export PYTHONIOENCODING=utf-8
rm -rf "$X"; mkdir -p "$X"
(cd "$P" && git archive HEAD) | tar -x -C "$X" || exit 1
FLAGS=""; for ch in $(echo "$CFG" | fold -w1); do FLAGS="$FLAGS --$ch"; done
python "$S/rb17_patch.py" "$X" $FLAGS || exit 1
cd "$X" || exit 1
FP=$(python -c "import sys; sys.path.insert(0,'experiments'); import dynamic_comparison as dc; print(dc.code_fingerprint())")
echo "adopted $CFG: fingerprint $FP"
python experiments/variant_sweep.py --variant base --keys rburst --seeds 0-9 --base-fp 4f08f48ac35c > "experiments/rb17_verify_$CFG.txt" 2>&1 || { echo "STOP: run failed"; exit 1; }
python - "$P/experiments/sweep_variant_f17${CFG}_4f08f48ac35c.jsonl" "experiments/sweep_variant_base_${FP}.jsonl" <<'EOF'
import json, sys
def load(p):
    d = {}
    for l in open(p):
        r = json.loads(l); d[(r["scenario"], r["n"], r["df"], r["seed"], r["key"])] = r
    return d
var, adopted = load(sys.argv[1]), load(sys.argv[2])
keys = sorted(adopted)
bad = [k for k in keys if not (k in var and bool(var[k].get("infeasible")) == bool(adopted[k].get("infeasible"))
       and var[k].get("error") == adopted[k].get("error") and var[k].get("mk") == adopted[k].get("mk")
       and var[k].get("cost") == adopted[k].get("cost") and var[k].get("misses") == adopted[k].get("misses"))]
print(f"  adopted vs variant, seeds 0-9: {len(keys) - len(bad)}/{len(keys)} rows identical")
sys.exit(1 if bad else 0)
EOF
