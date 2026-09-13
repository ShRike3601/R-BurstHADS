"""
Named counterfactual patches, applied inside a worker process before a
simulation runs. They exist to MEASURE a candidate change before deciding
whether it is a specification fix. Nothing here alters the simulator on
disk. A variant that gets adopted is written into the core code and kept
here only so the checkpoints that measured it stay reproducible from
their parent commit; on code after its adoption it is identical to base.

apply(name, kh=..., kr=...) first restores every attribute any variant has
patched, so a reused worker process cannot carry one variant's patch into
another variant's run.

Variants
--------
base
    The simulator exactly as it is on disk.

plan_ovh   [ADOPTED as fix 8, commit 042d1a9]
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


def _pre_fix1():
    """Undo fix 1 alone, on the current code.

    Restoring _fix_scratch/r_burst_hads.py.pre_migcheck would not isolate
    fix 1: that file also predates fixes 4-7, so a checkpoint against it
    measures five fixes at once. Instead this reverts only the two tests
    fix 1 changed (diff pre_migcheck -> pre_speedfix):
      tier 0  _select_replacement_vm: can_fit_task + estimate_finish_time
              <= D, instead of _check_migration
      tier 3  _provision_one_more: spot finish <= D, without the Section
              3.4 spare-time rule
    The reuse loop fix 1 deleted from _provision_one_more is not restored:
    before fix 1 it applied exactly tier 0's test to the same list, so it
    could never place anything tier 0 had not.
    """
    from models.vm import VM
    import scheduler.r_burst_hads as rb

    def _select_replacement_vm(self, task, current_time):
        for vm in self.provisioned_vms:
            if vm.state in (VM.HIBERNATED, VM.TERMINATED):
                continue
            if not vm.can_fit_task(task):
                continue
            if vm.estimate_finish_time(task, current_time) <= self.D:
                return vm
        return None

    def _provision_one_more(self, task, current_time):
        slack = self.D - current_time
        if slack > rb.STARTUP_LATENCY * rb.SLACK_MULTIPLIER:
            finish = (current_time + rb.STARTUP_LATENCY
                      + task.remaining_time / self._spot_tpl["speed"])
            if finish <= self.D:
                vm = self._create_spot_vm(
                    ready_time=current_time + rb.STARTUP_LATENCY)
                self.provisioned_vms.append(vm)
                return vm
        if (current_time + task.remaining_time / rb.BURST_SPEED) <= self.D:
            vm = self._create_vm(
                rb.BURST_TYPE, rb.BURST_SPEED, rb.BURST_RATE,
                rb.BURST_MEM_GB, 0.0, rb.BURST_VCPU,
                ready_time=current_time,
                extra_credits=rb.BURST_CREDITS_INIT,
                baseline_fraction=rb.BURST_BASELINE_FRAC,
            )
            self.provisioned_vms.append(vm)
            return vm
        return None

    _patch(rb.RBurstHADS, "_select_replacement_vm", _select_replacement_vm)
    _patch(rb.RBurstHADS, "_provision_one_more", _provision_one_more)


def _thm1(horizon):
    """Theorem 1 with P(v hibernates) taken over a chosen horizon.

    horizon="task": e_avg / vm.speed, exactly what the code on disk
        computes. Exists only to prove this copy of _preemptive_provision
        is faithful: variant thm1_copy must reproduce base bit-for-bit.
    horizon="D": the deadline, as the module docstring states Theorem 1,
        P(v hibernates) = 1 - exp(-lambda_v * D).
    """
    import scheduler.r_burst_hads as rb

    def _preemptive_provision(self):
        if not self.all_tasks:
            return
        n_tasks = len(self.all_tasks)
        e_avg   = sum(t.exec_time for t in self.all_tasks) / n_tasks
        od_rate = (min(self.ondemand_vms, key=lambda v: v.cost_rate
                      ).cost_rate if self.ondemand_vms else 0.085/3600)
        for vm in list(self.spot_vms):
            if vm.hibernation_rate <= 0:
                continue
            p_hib = vm.hibernation_probability(
                e_avg / vm.speed if horizon == "task" else self.D)
            if p_hib < rb.PREEMPTIVE_RISK_THRESHOLD:
                continue
            if self.solution:
                n_v = sum(1 for vid in self.solution.allocation.values()
                          if vid == vm.id)
            else:
                n_v = n_tasks // max(1, len(self.spot_vms))
            s_rate   = self._spot_tpl["cost_rate"]
            s_speed  = self._spot_tpl["speed"]
            theta_s  = s_speed * self._spot_tpl["vcpu"]
            od_vm    = (min(self.ondemand_vms, key=lambda v: v.cost_rate)
                        if self.ondemand_vms else None)
            theta_od = ((od_vm.speed * od_vm.vcpu_count) if od_vm else 4.0)
            EPSILON = 0.0
            c_reactive  = n_v * e_avg * (od_rate/theta_od - s_rate/theta_s)
            c_proactive = rb.STARTUP_LATENCY * s_rate + EPSILON
            if p_hib * c_reactive <= c_proactive:
                continue
            replacement = self._create_spot_vm(
                ready_time=rb.STARTUP_LATENCY,
            )
            self.provisioned_vms.append(replacement)

    return lambda: _patch(rb.RBurstHADS, "_preemptive_provision",
                          _preemptive_provision)


def _rb_predictors(with_overhead):
    """R-BurstHADS's own finish-time predictors, with or without the
    checkpoint overhead execution charges (fix 8's principle, applied to
    the scheduler fix 8 did not touch):
      _provision_one_more       spot finish and burstable finish
      _vms_needed_for_deadline  remaining work W
    The Section 3.4 spare-time rule keeps exec_time / speed, as
    BurstHADS._check_migration does.

    with_overhead=False reproduces the code on disk and exists only to
    prove the copy is faithful (variant rb_copy must equal base).
    """
    import math
    import scheduler.r_burst_hads as rb

    def f(task):
        return (1.0 + task.checkpoint_overhead) if with_overhead else 1.0

    def _provision_one_more(self, task, current_time):
        slack = self.D - current_time
        if slack > rb.STARTUP_LATENCY * rb.SLACK_MULTIPLIER:
            spot_speed = self._spot_tpl["speed"]
            finish     = (current_time + rb.STARTUP_LATENCY
                          + task.remaining_time / spot_speed * f(task))
            spare      = self.D - finish
            longest    = task.exec_time / spot_speed
            if finish <= self.D and spare > longest:
                vm = self._create_spot_vm(
                    ready_time=current_time + rb.STARTUP_LATENCY,
                )
                self.provisioned_vms.append(vm)
                return vm
        if (current_time + task.remaining_time / rb.BURST_SPEED * f(task)) <= self.D:
            vm = self._create_vm(
                rb.BURST_TYPE, rb.BURST_SPEED, rb.BURST_RATE,
                rb.BURST_MEM_GB, 0.0, rb.BURST_VCPU,
                ready_time=current_time,
                extra_credits=rb.BURST_CREDITS_INIT,
                baseline_fraction=rb.BURST_BASELINE_FRAC,
            )
            self.provisioned_vms.append(vm)
            return vm
        return None

    def _vms_needed_for_deadline(self, tasks, current_time, targets,
                                 use_spot, startup):
        W = sum(t.remaining_time * f(t) for t in tasks if not t.completed)
        if W <= 0:
            return 0
        T = self.D - current_time - startup
        if T <= 0:
            return 0
        existing = sum(v.speed * v.vcpu_count for v in targets)
        deficit  = (W / T) - existing
        if deficit <= 0:
            return 0
        if use_spot:
            per_vm = self._spot_tpl["speed"] * self._spot_tpl["vcpu"]
        else:
            per_vm = rb.BURST_SPEED * 1
        if per_vm <= 0:
            return 0
        return int(math.ceil(deficit / per_vm))

    def apply_patch():
        _patch(rb.RBurstHADS, "_provision_one_more", _provision_one_more)
        _patch(rb.RBurstHADS, "_vms_needed_for_deadline",
               _vms_needed_for_deadline)
    return apply_patch


def _burst_primary(order, sentinel):
    """Burst-HADS's primary-schedule predictions and Eq 9 scoring.

    order="id"    list-schedule each VM's tasks in task-id order, as
                  _compute_vm_load and _solution_task_finish_times do on
                  disk (they bucket by iterating all_tasks)
    order="exec"  list-schedule them memory-descending, the order
                  _apply_solution queues them and start_next_if_free
                  runs them (the greedy already plans in this order)

    sentinel="disk"  Eq 9 exactly as on disk: infeasible scores 1.0, cost
                     normalised by max SPOT rate x Dspot x |spot VMs|
    sentinel="inf"   infeasible scores +inf, as the reference IPDPS.py
                     does; feasible scores unchanged
    sentinel="norm"  infeasible scores 1.0, and the cost normaliser covers
                     every VM the search can place a task on: the spot
                     pool plus the on-demand VMs of the initial solution
                     (the ILS never adds on-demand VMs), at the dearest
                     rate among them -- the bound the paper's 1.0 relies on

    ("id", "disk") reproduces the code on disk and exists to prove these
    copies are faithful.
    """
    from models.vm import VM
    from scheduler.burst_hads import BurstHADS

    def _bucket(self, solution):
        vm_map, buckets = {vm.id: vm for vm in self.all_vms}, {}
        for task in self.all_tasks:
            vid = solution.allocation.get(task.task_id)
            if vid is not None:
                buckets.setdefault(vid, []).append(task)
        for vid, tasks in buckets.items():
            if order == "exec":
                tasks.sort(key=lambda t: t.memory_req, reverse=True)
        return vm_map, buckets

    def _compute_vm_load(self, solution):
        vm_map, buckets = _bucket(self, solution)
        vm_load = {}
        for vm_id, tasks in buckets.items():
            vm = vm_map.get(vm_id)
            if vm is None:
                continue
            vm_load[vm_id] = self._vm_makespan_static(tasks, vm)
        return vm_load

    def _solution_task_finish_times(self, solution):
        vm_map, buckets = _bucket(self, solution)
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

    orig_ils = BurstHADS._iterated_local_search

    def _iterated_local_search(self, initial, *a, **k):
        self._eq9_ondemand = [v for v in initial.selected_vms
                              if v.market == VM.ONDEMAND]
        return orig_ils(self, initial, *a, **k)

    def _fitness(self, solution, dspot):
        makespan, cost = self._evaluate(solution)
        if sentinel == "norm":
            pool = list(self.spot_vms) + list(getattr(self, "_eq9_ondemand", []))
            max_cost = (max(v.cost_rate for v in pool) * dspot * len(pool)
                        if pool else 0)
        elif self.spot_vms:
            max_cost = (max(v.cost_rate for v in self.spot_vms)
                        * dspot * len(self.spot_vms))
        else:
            max_cost = 0
        if makespan > dspot:
            return float("inf") if sentinel == "inf" else 1.0
        norm_cost     = cost / max_cost    if max_cost > 0 else 0
        norm_makespan = makespan / dspot   if dspot    > 0 else 0
        return (self.alpha * norm_cost
                + (1 - self.alpha) * norm_makespan)

    def apply_patch():
        _patch(BurstHADS, "_compute_vm_load", _compute_vm_load)
        _patch(BurstHADS, "_solution_task_finish_times",
               _solution_task_finish_times)
        _patch(BurstHADS, "_iterated_local_search", _iterated_local_search)
        _patch(BurstHADS, "_fitness", _fitness)
    return apply_patch


def _limits(markets):
    """Instance limits on (models/limits.py) for the given markets. Needs
    code that has the limits module; on older code apply() raises
    ImportError rather than silently measuring nothing."""
    def apply_patch():
        import models.limits as lim
        _patch(lim, "ENABLED", True)
        _patch(lim, "MARKETS", tuple(markets))
    return apply_patch


VARIANTS = {
    "base":             [],
    "cap_od":           [lambda: _limits(("ondemand",))()],
    "cap_all":          [lambda: _limits(("ondemand", "spot"))()],
    "b_copy":           [lambda: _burst_primary("id", "disk")()],
    "b_order":          [lambda: _burst_primary("exec", "disk")()],
    "b_inf":            [lambda: _burst_primary("id", "inf")()],
    "b_norm":           [lambda: _burst_primary("id", "norm")()],
    "b_order_inf":      [lambda: _burst_primary("exec", "inf")()],
    "b_order_norm":     [lambda: _burst_primary("exec", "norm")()],
    "plan_ovh":         [_plan_ovh],
    "repl_t9":          [_repl_t9],
    "plan_ovh+repl_t9": [_plan_ovh, _repl_t9],
    "pre_fix1":         [_pre_fix1],
    "thm1_copy":        [lambda: _thm1("task")()],
    "thm1_D":           [lambda: _thm1("D")()],
    "rb_copy":          [lambda: _rb_predictors(False)()],
    "rb_ovh":           [lambda: _rb_predictors(True)()],
}


def apply(name, kh=None, kr=None):
    if name not in VARIANTS:
        raise ValueError(f"unknown variant {name!r}; have {sorted(VARIANTS)}")
    _restore_all()
    _T9["kh"], _T9["kr"] = kh, kr
    for fn in VARIANTS[name]:
        fn()
