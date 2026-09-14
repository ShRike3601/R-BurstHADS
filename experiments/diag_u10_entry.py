"""
How the missed tasks reached the burstable they missed on. Reads
experiments/diag_u10.json (committed, 3772258) only; no simulation.

    python experiments\diag_u10_entry.py  -> experiments/diag_u10_entry.txt
"""
import json
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
res = json.load(open(HERE / "diag_u10.json"))
rows = [(tuple(x["unit"]), m) for x in res for m in x["missed"]]
lab = lambda e: e["path"] + (f" / {e['tier']}" if e["tier"] else "")
out = []
P = out.append
on_b = [(u, m) for u, m in rows if m["history"][-1]["market"] == "burstable"]
P(f"Missed tasks: {len(rows)}; last placed on a burstable: {len(on_b)}")
first_final, first_any, prev, owner, steal, baseline = Counter(), Counter(), Counter(), Counter(), 0, Counter()
for u, m in on_b:
    h = m["history"]
    fid = h[-1]["vm"]
    i = next(k for k, e in enumerate(h) if e["vm"] == fid)
    first_final[lab(h[i])] += 1
    first_any[lab(next(e for e in h if e["market"] == "burstable"))] += 1
    prev[(h[i - 1]["market"] + ":" + h[i - 1]["type"]) if i else "none"] += 1
    owner["R-BurstHADS-provisioned (id 100-9999)" if 100 <= fid < 10000 else
          "Burst-HADS proactive / new (id >= 10000)" if fid >= 10000 else "pool (id < 100)"] += 1
    steal += any(e["path"] == "work stealing" and e["market"] == "burstable" for e in h)
    baseline[str(sorted({d["baseline"] for d in m["dispatches"] if d["vm"] == fid}))] += 1
for title, c in (("Path that first put the task on the burstable it missed on", first_final),
                 ("Path that first put the task on any burstable", first_any),
                 ("VM the task came from just before that entry", prev),
                 ("Owner of that burstable", owner),
                 ("Baseline mode at its starts on that burstable", baseline)):
    P(f"\n{title}:")
    for k, v in c.most_common():
        P(f"  {v:4d}  {k}")
P(f"\nMissed tasks ever moved onto a burstable by work stealing (Algorithm 5): {steal}")
nr = Counter()
for u, m in rows:
    for e in m["history"]:
        if not e["ready"]:
            nr[f"{lab(e)} -> {e['market']}:{e['type']}"] += 1
P("\nPlacements onto a VM whose ProvisioningEvent had not yet run:")
for k, v in nr.most_common():
    P(f"  {v:4d}  {k}")
(HERE / "diag_u10_entry.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
