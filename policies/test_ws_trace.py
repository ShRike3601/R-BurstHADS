import random, sys, copy
sys.path.insert(0, '.')
from main import generate_tasks, compute_deadlines, build_vms_dburst
from models.job import Job; from models.stage import Stage
from models.utils import flatten_and_assign_deadlines
from simulation.event_engine import EventEngine
from simulation.execution_engine import start_execution
from simulation.events import HibernationEvent
from models.vm import VM
from scheduler.r_burst_hads import RBurstHADS

# Patch work_stealing to trace calls
import policies.work_stealing as ws_module
original_ws = ws_module.work_stealing
ws_calls = []

def traced_ws(idle_vm, busy_vms, jobs, current_time, scheduler):
    if current_time < 200:  # only trace early calls
        gains = []
        for vm in busy_vms:
            if len(vm.tasks) <= 1:
                continue
            for task in vm.tasks:
                if task.completed:
                    continue
                if current_time - task.last_migration_time < 3:
                    continue
                cs = scheduler.slack(task, vm, task.deadline, current_time)
                ns = scheduler.slack(task, idle_vm, task.deadline, current_time)
                gains.append((task.task_id, vm.id, cs, ns, ns-cs))
        ws_calls.append({
            't': current_time,
            'idle_vm': idle_vm.id,
            'busy': [(v.id, len(v.tasks)) for v in busy_vms if len(v.tasks)>1],
            'gains': gains[:3]
        })
    return original_ws(idle_vm, busy_vms, jobs, current_time, scheduler)

ws_module.work_stealing = traced_ws

random.seed(42)
tasks = generate_tasks(20)
gdl, _ = compute_deadlines(20, 1.0)
tc = copy.deepcopy(tasks)
for t in tc:
    t.stage_id=0; t.assigned_vm=None; t.start_time=None
    t.finish_time=None; t.completed=False; t.current_event=None
    t.exec_start_on_current_vm=None; t.checkpointed_remaining=None
    t.remaining_time=t.exec_time
job = Job(0, stages=[Stage(0, gdl, tc)])
all_tasks = flatten_and_assign_deadlines([job])
vms = build_vms_dburst()
sched = RBurstHADS(vms, all_tasks, [job], deadline=gdl)
sched.schedule(0)
engine = EventEngine(sched)
sched.event_engine = engine
start_execution(vms, 0, engine)
spot = [v for v in vms if v.is_spot]
t1 = max(spot, key=lambda v: v.hibernation_rate)
t2 = [v for v in spot if v.id != t1.id][0]
engine.add_event(HibernationEvent(90.0, t1, sched))
engine.add_event(HibernationEvent(105.0, t2, sched))
engine.run()

print(f"Total work stealing calls traced (t<200): {len(ws_calls)}")
for c in ws_calls[:8]:
    print(f"  t={c['t']:.0f} idle=VM{c['idle_vm']} "
          f"busy={c['busy']} gains={c['gains']}")

from metrics.metrics import Metrics
m = Metrics([job], vms)
s = m.summary()
rescued = sum(1 for t in tc if t.start_time and t.start_time > 105)
print(f"\nFinal: cost=${s['total_cost']:.6f} makespan={s['makespan']:.1f}s rescued={rescued}")
print(f"Provisioned: {sched.provisioning_summary()}")