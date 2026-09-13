"""
Named counterfactual patches, applied inside a worker process before a
simulation runs. They exist to MEASURE a candidate change before deciding
whether it is a specification fix. Nothing here alters the simulator on
disk; a variant that gets adopted is written into the core code and
deleted from this file.

apply(name, kh=..., kr=...) first restores every attribute any variant has
patched, so a reused worker process cannot carry one variant's patch into
another variant's run.

Variants
--------
base
    The simulator exactly as it is on disk.

plan_ovh
    The static planners predict a queue's finish with the same
    (1 + checkpoint_overhead) factor that execution charges. On disk
    VM.start_next_if_free always applies it and VM.estimate_finish_time
    mirrors that (see the comment there), but HADS._vm_makespan_static,
    BurstHADS._vm_makespan_static and BurstHADS._solution_task_finish_times
    do not. R-BurstHADS inherits Burst-HADS's planner, so it is covered.

repl_t9
    Under Table 9 scenarios, a spot VM launched mid-run enters the SAME
    Poisson hibernation/resume process as the pool's spot VMs,
    lambda_h = kh/D and lambda_r = kr/D, mirroring the loop in
    main.run_simulation from the VM's ready time. On disk it is exposed at
    its declared per-type rate instead (ProvisioningEvent.
    _expose_to_spot_risk, mode "declared"): 0.04/hr for c5.xlarge whatever
    kh is, while every c5.xlarge in the pool is hibernated at kh/D. Only
    R-BurstHADS launches spot VMs mid-run, so only it is affected.
"""

_ORIGINALS = {}                 # (owner, attr) -> value before patching
_T9 = {"kh": None, "kr": None}  # scenario rates for the run in progress


def _patch(owner, attr, value):
    key = (owner, attr)
    if key not in _ORIGINALS:
        _ORIGINALS[key] = getattr(owner, attr)
    setattr(owner, attr, value)


def _restore_all():
    for (owner, attr), value in _ORIGINALS.items():
        setattr(owner, attr, value)
    _ORIGINALS.clear()


def _plan_ovh():
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS

    def _vm_makespan_static(self, tasks, vm):
        cores = [0.0] * vm.vcpu_count
        for t in tasks:
            idx = cores.index(min(cores))
            cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
        return max(cores) if cores else 0.0

    def _solution_task_finish_times(self, solution):
        vm_map  = {vm.id: vm for vm in self.all_vms}
        buckets = {}
        for task in self.all_tasks:
            vid = solution.allocation.get(task.task_id)
            if vid is not None:
                buckets.setdefault(vid, []).append(task)
        finish = {}
        for vid, tasks in buckets.items():
            vm = vm_map.get(vid)
            if vm is None:
                continue
            cores = [0.0] * vm.vcpu_count
            for t in tasks:
                idx = cores.index(min(cores))
                cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
                finish[t] = cores[idx]
        return finish

    _patch(HADS, "_vm_makespan_static", _vm_makespan_static)
    _patch(BurstHADS, "_vm_makespan_static", _vm_makespan_static)
    _patch(BurstHADS, "_solution_task_finish_times", _solution_task_finish_times)


def _repl_t9():
    from simulation.provisioning_event import ProvisioningEvent
    original = ProvisioningEvent._expose_to_spot_risk

    def _expose_to_spot_risk(self):
        kh, kr = _T9["kh"], _T9["kr"]
        risk   = getattr(self.scheduler, "_spot_risk", None)
        vm     = self.new_vm
        if kh is None or not risk or not vm.is_spot:
            return original(self)
        engine = self.scheduler.event_engine
        if engine is None:
            return
        from simulation.events import HibernationEvent
        D     = risk["deadline"]
        lam_h = kh / D
        lam_r = (kr / D) if kr else 0.0
        rng   = risk["rng"]
        t = self.time + rng.expovariate(lam_h)
        while t < D:
            if lam_r > 0:
                back = t + rng.expovariate(lam_r)
                res  = back if back < D else None
            else:
                res = None
            engine.add_event(HibernationEvent(t, vm, self.scheduler,
                                              resume_time=res))
            if res is None:
                break
            t = res + rng.expovariate(lam_h)

    _patch(ProvisioningEvent, "_expose_to_spot_risk", _expose_to_spot_risk)


VARIANTS = {
    "base":             [],
    "plan_ovh":         [_plan_ovh],
    "repl_t9":          [_repl_t9],
    "plan_ovh+repl_t9": [_plan_ovh, _repl_t9],
}


def apply(name, kh=None, kr=None):
    if name not in VARIANTS:
        raise ValueError(f"unknown variant {name!r}; have {sorted(VARIANTS)}")
    _restore_all()
    _T9["kh"], _T9["kr"] = kh, kr
    for fn in VARIANTS[name]:
        fn()
