import random
from main import (generate_tasks, compute_deadlines, get_expected_makespan,
                   build_vms_dburst, run_simulation)
from scheduler.burst_hads import BurstHADS
from scheduler.r_burst_hads import RBurstHADS

random.seed(42)
n_tasks = 50
df = 1.0
tasks = generate_tasks(n_tasks)
global_deadline, _ = compute_deadlines(n_tasks, df)
avg_exec_on_m5 = 225.0 / 4
hib_time = [max(1.0, avg_exec_on_m5 * 0.5), max(1.0, avg_exec_on_m5 * 2.5)]

for label, cls in [("BurstHADS", BurstHADS), ("D-BurstHADS", RBurstHADS)]:
    random.seed(42)
    m = run_simulation(cls, tasks, global_deadline,
                        hibernation_time=hib_time,
                        vm_builder=build_vms_dburst,
                        hibernate_high_risk=True)
    all_tasks = [t for job in m.jobs for stage in job.stages for t in stage.tasks]
    n_none = sum(1 for t in all_tasks if t.finish_time is None)
    n_baseline = sum(1 for t in all_tasks if getattr(t, "baseline_mode", False))
    vm_ids_used = sorted(set(t.assigned_vm.id for t in all_tasks if t.assigned_vm))
    print(f"--- {label} ---")
    print(f"  tasks total={len(all_tasks)}  finish_time=None: {n_none}  baseline_mode tasks: {n_baseline}")
    print(f"  distinct vm ids used: {vm_ids_used}")
    for vm in m.vms:
        n_assigned = sum(1 for t in all_tasks if t.assigned_vm is vm)
        print(f"    vm id={vm.id} type={vm.vm_type} market={vm.market} vcpu={vm.vcpu_count} "
              f"state={vm.state} tasks_ever_assigned~{n_assigned} billed_s={vm.billed_seconds(m.makespan()):.1f} "
              f"credits={vm.cpu_credits}")
    print(f"  makespan={m.makespan():.1f} cost=${m.total_cost():.6f} misses={m.deadline_misses()}")
