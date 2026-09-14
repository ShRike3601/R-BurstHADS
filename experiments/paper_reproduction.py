"""
Reproduction of Teylo et al., Burst-HADS (IEEE TCC) Table 10.

Purpose: validate our HADS and BurstHADS ports against the source paper's
own published comparison before using either as a baseline for R-BurstHADS.

Everything here mirrors the paper rather than this thesis's own choices:

  Table 4  VM catalogue (Nov-2020 us-east-1 prices)
  Table 7  jobs J60 / J80 / J100 / ED200, with their real exec-time and
           memory ranges
           D = 2700 s for every job (fixed, NOT scaled with n)
  Table 9  hibernation scenarios, per-VM Poisson lambda_h = kh/D and
           lambda_r = kr/D:
             sc1 kh=1 kr=0 | sc2 kh=5 kr=0 | sc3 kh=1 kr=5
             sc4 kh=5 kr=5 | sc5 kh=3 kr=2.5
  Alg. 1   alpha=0.5, burst_rate=0.2, max_iteration=200, max_attempt=50,
           swap_rate=0.10, max_failed=20, relaxed_rate=0.25, AC=900 s

Paper's headline (Section 5): "Compared to HADS, Burst-HADS reduces the
makespan in 44.37%, 42.09%, 28.82%, and 11.82%, for jobs J60, J80, J100
and ED200" while "the average increase of Burst-HADS monetary cost is
1.92% compared to HADS." Note the direction: Burst-HADS is FASTER and
slightly MORE EXPENSIVE. It improves cost only in sc2 and sc5.

NOTE on `speed`: this codebase splits a VM's processing capacity into
`speed` (per-task speedup) and `vcpu_count` (concurrent slots). Instances
of the same family share a per-core clock, so speed is held constant here
and only vcpu_count varies with instance size -- c3.xlarge is 4 cores, not
4 cores each twice as fast as c3.large's.
"""
import sys, random, io, contextlib, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.task import Task
from models.vm import VM
from main import run_simulation
from scheduler.hads         import HADS
from scheduler.burst_hads   import BurstHADS
from scheduler.r_burst_hads import RBurstHADS

DEADLINE = 2700.0
CORE_SPEED = 1   # exec_time is measured wall-clock on one core, so 1 unit/s

# Table 7
JOBS = {
    "J60":   dict(n=60,  ex=(102, 323), mem=(2.85, 12.20)),
    "J80":   dict(n=80,  ex=(103, 322), mem=(2.91, 13.19)),
    "J100":  dict(n=100, ex=(107, 330), mem=(2.81, 10.86)),
    "ED200": dict(n=200, ex=(161, 354), mem=(153.0, 177.0)),
}

# Table 9
SCENARIOS = {
    "sc1": dict(kh=1.0, kr=0.0),
    "sc2": dict(kh=5.0, kr=0.0),
    "sc3": dict(kh=1.0, kr=5.0),
    "sc4": dict(kh=5.0, kr=5.0),
    "sc5": dict(kh=3.0, kr=2.5),
}

# Paper Table 10 values we were able to extract, for side-by-side checking
PAPER = {
    ("J60","sc1"):   dict(hads=(0.091, 2620), burst=(0.119, 1274)),
    ("J60","sc2"):   dict(hads=(0.257, 2549), burst=(0.204, 1277)),
    ("J80","sc1"):   dict(hads=(0.150, 2581), burst=(0.167, 1419)),
    ("J100","sc2"):  dict(hads=(0.353, 2518), burst=(0.212, 1900)),
    ("ED200","sc1"): dict(hads=(0.314, 2680), burst=(0.388, 2327)),
}
PAPER_MK_REDUCTION = {"J60": 44.37, "J80": 42.09, "J100": 28.82, "ED200": 11.82}


def build_vms_paper(copies=6):
    """
    Table 4 catalogue. `copies` instances of each spot type so the ILS has
    room to select -- the paper states no per-type limit, so the deadline
    is meant to be the binding constraint, not pool size.
    """
    vms, vid = [], 0
    spec = [
        # (type,      vcpu, mem_gb, spot_rate, hib_rate_per_s)
        ("c3.large",  2, 3.75, 0.0299, 1.0/2700),
        ("c4.large",  2, 3.75, 0.0366, 1.0/2700),
        ("c3.xlarge", 4, 7.50, 0.0634, 1.0/2700),
    ]
    for _ in range(copies):
        for t, vcpu, mem, rate, hib in spec:
            vms.append(VM(vid, t, VM.SPOT, speed=CORE_SPEED,
                          cost_rate=rate/3600, memory_gb=mem,
                          hibernation_rate=hib, vcpu_count=vcpu))
            vid += 1
    # burstable (Table 4 t3.large) -- Burst-HADS launches more elastically
    vms.append(VM(vid, "t3.large", VM.BURSTABLE, speed=CORE_SPEED,
                  cost_rate=0.0832/3600, memory_gb=8.0,
                  baseline_fraction=0.20, hibernation_rate=0.0,
                  vcpu_count=2)); vid += 1
    # on-demand types (M^o), TCC23 Table 3's on-demand prices; Attempt 3
    # walks them by price, each within its instance limit
    for t, vcpu, mem, rate in (("c4.large",  2, 3.75, 0.100),
                               ("c3.large",  2, 3.75, 0.105),
                               ("c3.xlarge", 4, 7.50, 0.199)):
        vms.append(VM(vid, t, VM.ONDEMAND, speed=CORE_SPEED,
                      cost_rate=rate/3600, memory_gb=mem,
                      hibernation_rate=0.0, vcpu_count=vcpu))
        vid += 1
    return vms


def gen_job(spec, seed):
    random.seed(seed)
    return [Task(i, job_id=0, stage_id=0,
                 exec_time=random.randint(spec["ex"][0], spec["ex"][1]),
                 memory_req=random.uniform(spec["mem"][0], spec["mem"][1]))
            for i in range(spec["n"])]


def one(cls, job_spec, sc, seed, copies):
    tasks = gen_job(job_spec, seed)
    f = io.StringIO()
    try:
        with contextlib.redirect_stdout(f):
            m = run_simulation(cls, tasks, DEADLINE,
                               vm_builder=lambda: build_vms_paper(copies),
                               kh=sc["kh"], kr=sc["kr"],
                               spot_risk_seed=seed)
        r = m.summary()
        allt = [t for j in m.jobs for s in j.stages for t in s.tasks]
        pct = sum(1 for t in allt if t.completed) / max(1, len(allt)) * 100
        return r["total_cost"], r["makespan"], r["deadline_misses"], pct, None
    except Exception as e:
        return None, None, None, None, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="J60,J80,J100")
    ap.add_argument("--scenarios", default="sc1,sc2")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--copies", type=int, default=3)   # ~9 spot VMs: the regime where HADS sits near D and the ILS has room to spread
    a = ap.parse_args()

    print(f"Burst-HADS Table 10 reproduction | D={DEADLINE:.0f}s | "
          f"{a.seeds} seeds | {a.copies} instances per spot type\n")
    for jname in a.jobs.split(","):
        spec = JOBS[jname]
        for scname in a.scenarios.split(","):
            sc = SCENARIOS[scname]
            out = {}
            for cls, key in ((HADS, "hads"), (BurstHADS, "burst"),
                             (RBurstHADS, "rburst")):
                cs, ms, mis, errs = [], [], 0, 0
                for sd in range(a.seeds):
                    c, mk, mi, pct, err = one(cls, spec, sc, sd, a.copies)
                    if err: errs += 1
                    else:   cs.append(c); ms.append(mk); mis += mi
                out[key] = (sum(cs)/len(cs) if cs else float('nan'),
                            sum(ms)/len(ms) if ms else float('nan'), mis, errs)
            h, b = out["hads"], out["burst"]
            red = (h[1]-b[1])/h[1]*100 if h[1] and h[1] == h[1] else float('nan')
            dcost = (b[0]-h[0])/h[0]*100 if h[0] and h[0] == h[0] else float('nan')
            print(f"{jname} {scname}")
            for key, label in (("hads","HADS"),("burst","BurstHADS"),
                               ("rburst","R-BurstHADS")):
                c, mk, mis, errs = out[key]
                print(f"    {label:<12} cost=${c:.4f}  makespan={mk:7.1f}s  "
                      f"misses={mis}  errors={errs}")
            print(f"    -> BurstHADS vs HADS: makespan {red:+.2f}%  cost {dcost:+.2f}%")
            pk = PAPER.get((jname, scname))
            if pk:
                pr = (pk['hads'][1]-pk['burst'][1])/pk['hads'][1]*100
                pc = (pk['burst'][0]-pk['hads'][0])/pk['hads'][0]*100
                print(f"       PAPER Table 10:  HADS ${pk['hads'][0]:.3f}/{pk['hads'][1]}s"
                      f"   Burst ${pk['burst'][0]:.3f}/{pk['burst'][1]}s"
                      f"   -> makespan {-pr:+.2f}%  cost {pc:+.2f}%")
            print()
    print("Paper's stated makespan reductions vs HADS: " +
          ", ".join(f"{k} {v}%" for k, v in PAPER_MK_REDUCTION.items()))
