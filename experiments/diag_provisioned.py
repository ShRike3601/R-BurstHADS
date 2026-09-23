"""
Record-only probe (experiments/util_plan.md): what R-BurstHADS's provisioned
capacity costs and how busy it is, by bag size, at DF 2.0.

    python experiments\\diag_provisioned.py > experiments\\diag_provisioned.txt

Busy time is measured where the simulator itself marks execution: a task's
`exec_start_on_current_vm` is set in `VM.start_next_if_free` and cleared at
task completion and at a checkpoint, so wrapping those three closes every
interval a task actually ran. Cost is the same billing the metric uses, per
VM. Every probed run must reproduce its committed sweep row exactly.
"""
import sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE.parent), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

FP = "2439a00d7f74"
CONFIGS = {  # label -> (variant, reference sweep file)
    "faithful (TCC23 §3.2 in full)": ("ref_p2", f"experiments/sweep_variant_ref_p2_{FP}.jsonl"),
    "guard kept (as frozen)": ("base", f"experiments/sweep_raw_{FP}.jsonl"),
}
NS = (50, 100, 200, 300)
SCS = ("sc1", "sc2", "sc3", "sc4", "sc5")


def probe(arg):
    label, unit = arg
    for p in (str(HERE.parent), str(HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import variants
    import dynamic_comparison as dcw
    from models.vm import VM
    from models.task import Task
    from scheduler.r_burst_hads import RBurstHADS
    import simulation.events as ev

    variant = CONFIGS[label][0]
    t9 = dcw.TABLE9.get(unit[0])
    variants.apply(variant, kh=t9["kh"] if t9 else None, kr=t9["kr"] if t9 else None)

    busy = defaultdict(float)      # vm id -> executed core-seconds
    open_iv = {}                   # task id -> (vm id, start)
    holder = {}
    saved = []

    def close(task, when):
        iv = open_iv.pop(id(task), None)
        if iv is not None:
            busy[iv[0]] += max(0.0, when - iv[1])

    o_start = VM.start_next_if_free

    def start_next_if_free(self, current_time, engine):
        out = o_start(self, current_time, engine)
        for t in list(self.running):
            if t.exec_start_on_current_vm is not None and id(t) not in open_iv:
                open_iv[id(t)] = (self.id, t.exec_start_on_current_vm)
        return out

    o_ckpt = Task.save_checkpoint

    def save_checkpoint(self, current_time, *a, **k):
        close(self, current_time)
        return o_ckpt(self, current_time, *a, **k)

    o_done = ev.TaskCompleteEvent.execute

    def execute(self):
        close(self.task, self.time)
        return o_done(self)

    o_init = RBurstHADS.__init__

    def __init__(self, *a, **k):
        o_init(self, *a, **k)
        holder["s"] = self

    for owner, attr, fn in ((VM, "start_next_if_free", start_next_if_free),
                            (Task, "save_checkpoint", save_checkpoint),
                            (ev.TaskCompleteEvent, "execute", execute),
                            (RBurstHADS, "__init__", __init__)):
        saved.append((owner, attr, getattr(owner, attr)))
        setattr(owner, attr, fn)
    try:
        row = dcw.run_one_unit((*unit, FP))
    finally:
        for owner, attr, orig in saved:
            setattr(owner, attr, orig)

    sched = holder.get("s")
    if sched is None or not row or row.get("error") or row.get("infeasible"):
        return label, unit, row, None

    for t in list(open_iv):
        open_iv.pop(t)
    vms = list(sched.all_vms)
    closed = [e for vm in vms for _s, e in vm._billing_intervals if e is not None]
    finishes = [t.finish_time for t in sched.all_tasks if t.finish_time is not None]
    sim_end = max(closed + [max(finishes)]) if (closed or finishes) else 0.0

    def cost_of(vm):
        return vm.cost_rate * vm.billed_seconds(sim_end)

    prov = [vm for vm in getattr(sched, "provisioned_vms", []) if vm.billed_seconds(sim_end) > 0]
    billed_p = sum(vm.billed_seconds(sim_end) for vm in prov)
    capacity_p = sum(vm.billed_seconds(sim_end) * vm.vcpu_count for vm in prov)
    busy_p = sum(busy.get(vm.id, 0.0) for vm in prov)
    billed_all = sum(vm.billed_seconds(sim_end) for vm in vms if vm.billed_seconds(sim_end) > 0)
    capacity_all = sum(vm.billed_seconds(sim_end) * vm.vcpu_count for vm in vms)
    stat = dict(
        cost_total=sum(cost_of(vm) for vm in vms),
        cost_prov=sum(cost_of(vm) for vm in prov),
        n_prov=len(prov),
        n_fleet=sum(1 for vm in vms if vm.billed_seconds(sim_end) > 0),
        billed_prov=billed_p, billed_all=billed_all,
        busy_prov=busy_p, busy_all=sum(busy.values()),
        cap_prov=capacity_p, cap_all=capacity_all,
    )
    return label, unit, row, stat


def main():
    import results_pack as rp
    refs = {lab: rp.load_jsonl(f) for lab, (_v, f) in CONFIGS.items()}
    jobs = [(lab, (sc, n, 2.0, seed, "rburst"))
            for lab in CONFIGS for sc in SCS for n in NS for seed in range(30)]
    with Pool() as pool:
        out = [r for r in pool.imap_unordered(probe, jobs, chunksize=4)]

    print(f"diag_provisioned on {FP}: R-BurstHADS, DF 2.0, {len(out)} runs "
          f"({len(out) // len(CONFIGS)} per configuration), pre-registration experiments/util_plan.md")
    for lab in CONFIGS:
        rows = [(u, r) for l, u, r, _s in out if l == lab]
        same = sum(1 for u, r in rows if rp._same_row(r, refs[lab][u], exact=True))
        cost_ok = sum(1 for l, u, r, s in out if l == lab and s and abs(s["cost_total"] - r["cost"]) < 1e-9)
        print(f"- {lab}: rows identical to the committed sweep {same}/{len(rows)}; "
              f"per-VM cost reproduces the metric in {cost_ok}/{len(rows)} runs")

    print("\n| configuration | n | runs | provisioned VMs per run | fleet VMs per run | "
          "provisioned share of cost | provisioned utilisation | whole-fleet utilisation |")
    print("|---|---|---|---|---|---|---|---|")
    for lab in CONFIGS:
        for n in NS:
            sel = [s for l, u, r, s in out if l == lab and s and u[1] == n]
            if not sel:
                continue
            share = rp.mean(s["cost_prov"] / s["cost_total"] for s in sel if s["cost_total"])
            util_p = [s["busy_prov"] / s["cap_prov"] for s in sel if s["cap_prov"] > 0]
            util_a = [s["busy_all"] / s["cap_all"] for s in sel if s["cap_all"] > 0]
            print(f"| {lab} | {n} | {len(sel)} | {rp.mean(s['n_prov'] for s in sel):.2f} | "
                  f"{rp.mean(s['n_fleet'] for s in sel):.2f} | {100 * share:.1f}% | "
                  f"{100 * rp.mean(util_p):.1f}% (n={len(util_p)}) | {100 * rp.mean(util_a):.1f}% |")

    print("\nPooled over runs (total busy core-seconds / total billed core-seconds), by bag size:")
    for lab in CONFIGS:
        parts = []
        for n in NS:
            sel = [s for l, u, r, s in out if l == lab and s and u[1] == n]
            cap = sum(s["cap_prov"] for s in sel)
            parts.append(f"n={n}: {100 * sum(s['busy_prov'] for s in sel) / cap:.1f}%" if cap else f"n={n}: -")
        print(f"- {lab}: " + "; ".join(parts))


if __name__ == "__main__":
    main()
