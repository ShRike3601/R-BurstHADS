"""
Instrumented run: records what EVERY VM is doing at every event, for all
three schedulers on an identical workload and identical interruption stream.
Writes trace_<key>.json into experiments/trace_out/.
"""
import sys, json, random, io, contextlib
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from models.vm import VM
import simulation.event_engine as ee
import simulation.events as ev
import simulation.provisioning_event as pe
import simulation.resume_event as re_
import simulation.allocation_cycle_event as ace
from main import run_simulation, generate_tasks, compute_deadlines, build_vms_dburst
from scheduler.hads import HADS
from scheduler.burst_hads import BurstHADS
from scheduler.r_burst_hads import RBurstHADS

OUT = ROOT / "experiments" / "trace_out"; OUT.mkdir(exist_ok=True)
N    = int(sys.argv[1]) if len(sys.argv) > 1 else 40
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 0
KH   = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
KR   = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0

LOG = {"snap": [], "events": []}

def snapshot(t, vms):
    row = {"t": round(t, 2), "vms": []}
    for v in vms:
        row["vms"].append({
            "id": v.id, "type": v.vm_type, "mkt": v.market,
            "state": v.state, "run": len(v.running), "q": len(v.tasks),
            "cr": (round(v.cpu_credits, 2) if v.cpu_credits is not None else None),
            "bill": round(v.billed_seconds(t), 1),
        })
    LOG["snap"].append(row)

def note(t, kind, vm, msg):
    LOG["events"].append({"t": round(t, 2), "kind": kind,
                          "vm": (f"{vm.vm_type}#{vm.id}" if vm else ""), "msg": msg})

# ---- hooks -------------------------------------------------------------
_hib = ev.HibernationEvent.execute
def hib(self):
    if self.vm.state not in (VM.HIBERNATED, VM.TERMINATED):
        note(self.time, "HIBERNATE", self.vm,
             f"suspended holding {len([t for t in self.vm.tasks if not t.completed])} unfinished task(s)")
        before = [t for t in self.vm.tasks if not t.completed]
        r = _hib(self)
        for t in before:
            dest = t.assigned_vm
            if dest is not None and dest is not self.vm:
                mode = "baseline" if getattr(t, "baseline_mode", False) else "burst/full"
                note(self.time, "MIGRATE", dest,
                     f"task {t.task_id} rescued here, {t.remaining_time:.0f}s work left, {mode} mode")
        return r
    return _hib(self)
ev.HibernationEvent.execute = hib

_tc = ev.TaskCompleteEvent.execute
def tc(self):
    ok = (self.task.current_event == self) and not self.task.completed
    cr0 = self.vm.cpu_credits
    r = _tc(self)
    if ok and self.vm.is_burstable and cr0 is not None:
        d = self.vm.cpu_credits - cr0
        note(self.time, "CREDITS", self.vm,
             f"task {self.task.task_id} done, credits {cr0:.1f} -> {self.vm.cpu_credits:.1f} ({d:+.1f})")
    return r
ev.TaskCompleteEvent.execute = tc

_pv = pe.ProvisioningEvent.execute
def pv(self):
    note(self.time, "PROVISION", self.new_vm, "came online and started billing")
    return _pv(self)
pe.ProvisioningEvent.execute = pv

_rs = re_.ResumeEvent.execute
def rs(self):
    if self.vm.state == VM.HIBERNATED:
        note(self.time, "RESUME", self.vm, "came back, empty, will try to steal work")
    return _rs(self)
re_.ResumeEvent.execute = rs

_ac = ace.AllocationCycleEvent.execute
def ac(self):
    was = self.vm.state
    r = _ac(self)
    if was != VM.TERMINATED and self.vm.state == VM.TERMINATED:
        note(self.time, "TERMINATE", self.vm, "idle 900s, shut down to stop billing")
    return r
ace.AllocationCycleEvent.execute = ac

_run = ee.EventEngine.run
def run(self):
    snapshot(0.0, self.scheduler.vms)
    while self.events:
        self.events.sort(key=lambda e: e.time)
        e = self.events.pop(0)
        self.time = e.time
        e.execute()
        snapshot(self.time, self.scheduler.vms)
ee.EventEngine.run = run

# ---- run all three -----------------------------------------------------
D, _ = compute_deadlines(N, 1.0, 1)
for cls, key in ((HADS, "hads"), (BurstHADS, "burst"), (RBurstHADS, "rburst")):
    LOG["snap"], LOG["events"] = [], []
    random.seed(SEED); tasks = generate_tasks(N)
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        m = run_simulation(cls, tasks, D, vm_builder=build_vms_dburst,
                            kh=KH, kr=KR, spot_risk_seed=SEED)
    s = m.summary()
    out = {"scheduler": key, "n": N, "seed": SEED, "kh": KH, "kr": KR,
           "deadline": D, "summary": s,
           "snapshots": LOG["snap"], "events": LOG["events"]}
    (OUT / f"trace_{key}.json").write_text(json.dumps(out))
    nb = sum(1 for e in LOG["events"] if e["kind"] == "MIGRATE" and "t3" in e["vm"])
    print(f"{key:<7} mk={s['makespan']:7.1f}  cost=${s['total_cost']:.4f}  "
          f"D={D:.0f}  events={len(LOG['events'])}  snapshots={len(LOG['snap'])}  "
          f"rescues onto burstable={nb}")
