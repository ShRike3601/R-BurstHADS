import random
from models.vm import VM
from models.task import Task
from models.job import Job
from models.stage import Stage
from models.utils import flatten_and_assign_deadlines
from scheduler.burst_hads import BurstHADS
from simulation.event_engine import EventEngine
from simulation.execution_engine import start_execution

print("=== Test 1: multi-core concurrency ===")
vm = VM(0, "c5.xlarge", VM.SPOT, speed=4, cost_rate=0.06/3600, memory_gb=16.0, vcpu_count=4)
tasks = [Task(i, 0, 0, exec_time=100, memory_req=1.0) for i in range(6)]
for t in tasks:
    t.assigned_vm = vm
vm.tasks = list(tasks)

class FakeEngine:
    def __init__(self): self.events = []
    def add_event(self, e): self.events.append(e)

eng = FakeEngine()
vm.start_next_if_free(0.0, eng)
print(f"  running count (expect 4, vcpu=4): {len(vm.running)}")
print(f"  events scheduled (expect 4): {len(eng.events)}")
print(f"  is_deployed after dispatch: {vm.is_deployed}")
finish_times = sorted(e.time for e in eng.events)
print(f"  finish times of first 4: {finish_times}")

print()
print("=== Test 2: WRR distribution across spot VMs (Eq 8) ===")
random.seed(1)
vms = [
    VM(0, "c5.large",  VM.SPOT, speed=2, cost_rate=0.03/3600, memory_gb=100.0, vcpu_count=2),
    VM(1, "c5.xlarge",  VM.SPOT, speed=4, cost_rate=0.06/3600, memory_gb=100.0, vcpu_count=4),
]
tasks = [Task(i, 0, 0, exec_time=random.randint(100,350), memory_req=1.0) for i in range(40)]
job = Job(0, [Stage(0, deadline=100000, tasks=tasks)])
all_tasks = flatten_and_assign_deadlines([job])
sched = BurstHADS(vms, all_tasks, [job], deadline=100000, burst_rate=0.5)
sched.schedule(0)
from collections import Counter
counts = Counter(sched.solution.allocation.values())
print(f"  weight(vm0 c5.large)={sched.wrr_weight(vms[0]):.1f}  weight(vm1 c5.xlarge)={sched.wrr_weight(vms[1]):.1f}")
print(f"  task counts per vm id: {dict(counts)}  (both should be used, not 100% on one)")

print()
print("=== Test 3: proactive burstable allocation (Algorithm 1 Part 2) ===")
n_selected = len(sched.solution.selected_vms)
print(f"  selected_vms count: {n_selected}, burst_rate=0.5 -> expect n={round(0.5*max(1,n_selected))}")
baseline_tasks = [t for t in all_tasks if getattr(t, 'baseline_mode', False)]
burstable_vm_ids_used = set(t.assigned_vm.id for t in baseline_tasks if t.assigned_vm)
print(f"  tasks flagged baseline_mode=True: {len(baseline_tasks)}")
print(f"  burstable vm ids they landed on: {burstable_vm_ids_used}")
print(f"  scheduler.burstable_vms ids after allocation: {[v.id for v in sched.burstable_vms]}")

print()
print("=== Test 4: full run compiles/executes end to end with new VMs ===")
engine = EventEngine(sched)
sched.event_engine = engine
start_execution(vms + sched.burstable_vms, 0, engine)
engine.run()
n_done = sum(1 for t in all_tasks if t.completed)
n_none = sum(1 for t in all_tasks if t.finish_time is None)
print(f"  tasks completed: {n_done}/{len(all_tasks)}  finish_time=None: {n_none}")
