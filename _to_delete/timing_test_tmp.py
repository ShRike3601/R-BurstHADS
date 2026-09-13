import time, random, sys
sys.path.insert(0, ".")
from main import run_simulation, generate_tasks, compute_deadlines, build_vms_rburst
from scheduler.burst_hads import BurstHADS
from scheduler.r_burst_hads import RBurstHADS

for n in [50, 300]:
    for cls in [BurstHADS, RBurstHADS]:
        random.seed(1)
        tasks = generate_tasks(n)
        gdl, _ = compute_deadlines(n, 1.0)
        t0 = time.time()
        m = run_simulation(cls, tasks, gdl, vm_builder=build_vms_rburst,
                            hibernation_time=[gdl*0.1, gdl*0.3])
        dt = time.time() - t0
        s = m.summary()
        print(f"n={n:4d} {cls.__name__:12s} time={dt:.3f}s  makespan={s['makespan']:.1f} cost={s['total_cost']:.4f}")
