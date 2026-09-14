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


def _nocap():
    """Instance limits off (models/limits.py ENABLED = False)."""
    def apply_patch():
        import models.limits as lim
        _patch(lim, "ENABLED", False)
    return apply_patch


def _migrate_to_launched(only_launched):
    """Which VMs the baselines' migration may choose.

    only_launched=False reproduces the code on disk: HADS.select_vm stages
    1-2 and BurstHADS._attempt_paper_migration Attempts 1-2 accept any pool
    VM that is not hibernated or terminated, including pool VMs the run
    never launched. Exists to prove this copy is faithful.
    only_launched=True restricts them to VMs the run has launched
    (self._launches). Algorithm 4's inputs are "the sets of idle, busy, and
    non-launched regular on-demand VMs (IR, BR and Mo)": running VMs, plus
    not-yet-launched ON-DEMAND VMs for the last resort, which
    _attempt_ondemand_fallback still draws from. CCScheduler's idle and
    working dispatchers are likewise running instances.
    """
    from models.vm import VM
    from scheduler.hads import HADS
    from scheduler.burst_hads import BurstHADS

    def ok(self, v):
        return (not only_launched) or v.id in self._launches._ids

    def hads_select_vm(self, task, job, current_time):
        deadline = self.D
        idle = [v for v in (self.spot_vms + self.ondemand_vms)
                if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                and not v.tasks and ok(self, v)]
        for vm in sorted(idle, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm
        working = [v for v in (self.spot_vms + self.ondemand_vms)
                   if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                   and v.tasks and ok(self, v)]
        for vm in sorted(working, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm
        return self._attempt_ondemand_fallback(task, current_time)

    def burst_attempt(self, task, current_time):
        deadline = self.D
        idle_burstable = [v for v in self.burstable_vms
                          if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                          and not v.tasks and ok(self, v)]
        for vm in sorted(idle_burstable, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time,
                                              deadline, burst_mode=True)):
                self._launches.commit(vm)
                return vm

        def _k_sort_key(v):
            market_rank = 0 if v.is_spot else 1
            busy_rank = 1 if v.tasks else 0
            return (market_rank, busy_rank, v.cost_rate)

        active = [v for v in (self.spot_vms + self.ondemand_vms)
                  if v.state not in (VM.HIBERNATED, VM.TERMINATED) and ok(self, v)]
        for vm in sorted(active, key=_k_sort_key):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm
        return None

    def apply_patch():
        _patch(HADS, "select_vm", hads_select_vm)
        _patch(BurstHADS, "_attempt_paper_migration", burst_attempt)
    return apply_patch


def _burst_fill(guard):
    """Burst-HADS's proactive burstable allocation (Algorithm 1, Part 2).

    guard=True reproduces the code on disk: a task moves to a burstable VM
    only if its baseline-mode finish beats its planned finish, so a launched
    burstable can stay idle (and, since billing starts at first dispatch,
    unbilled). Exists to prove this copy is faithful.
    guard=False follows the paper's text: Dspot violators move to the
    burstable VMs, and "if a burstable VM remains idle, the task with the
    latest finishing time in the scheduling map is moved to it".
    """
    import math
    from scheduler.burst_hads import BurstHADS

    def _allocate_burstable_vms(self, solution):
        n = math.ceil(self.burst_rate * max(1, len(solution.selected_vms)))
        if n <= 0:
            return solution
        burst_pool = self._launch_burstable_vms(n)
        if not burst_pool:
            return solution
        vm_map = {vm.id: vm for vm in self.all_vms}
        remaining_burst = list(burst_pool)

        finish_times = self._solution_task_finish_times(solution)
        violators = [(task, ft) for task, ft in finish_times.items()
                     if ft > self.Dspot]
        violators.sort(key=lambda pair: pair[1], reverse=True)
        for task, ft in violators:
            if not remaining_burst:
                break
            burst_vm = remaining_burst[0]
            old_vm = vm_map.get(solution.allocation.get(task.task_id))
            if old_vm is None or not burst_vm.can_fit_task(task):
                continue
            if guard and self._baseline_finish(task, burst_vm) >= ft:
                continue
            task.baseline_mode = True
            solution.allocation[task.task_id] = burst_vm.id
            if burst_vm not in solution.selected_vms:
                solution.selected_vms.append(burst_vm)
            remaining_burst.pop(0)

        if remaining_burst:
            finish_times = self._solution_task_finish_times(solution)
            candidates = sorted(finish_times.items(),
                                key=lambda pair: pair[1], reverse=True)
            for task, ft in candidates:
                if not remaining_burst:
                    break
                burst_vm = remaining_burst[0]
                old_vm_id = solution.allocation.get(task.task_id)
                if old_vm_id == burst_vm.id or not burst_vm.can_fit_task(task):
                    continue
                if guard and self._baseline_finish(task, burst_vm) >= ft:
                    continue
                task.baseline_mode = True
                solution.allocation[task.task_id] = burst_vm.id
                if burst_vm not in solution.selected_vms:
                    solution.selected_vms.append(burst_vm)
                remaining_burst.pop(0)
        return solution

    return lambda: _patch(BurstHADS, "_allocate_burstable_vms",
                          _allocate_burstable_vms)


def _no_release():
    """Fix 3's predecessor: surviving VMs are NOT terminated when the last
    task completes (TaskCompleteEvent._release_fleet_if_done is a no-op), so
    idle VMs run to their 900 s allocation cycle and hibernated ones can
    resume after the job. Together with the pre-fix-2 cost rule computed
    post hoc (diag_cost_gap's PRE2), this is the billing before fixes 2-3."""
    def apply_patch():
        import simulation.events as ev
        _patch(ev.TaskCompleteEvent, "_release_fleet_if_done", lambda self: None)
    return apply_patch


def _t9_deployed():
    """Table 8's hibernation process on DEPLOYED spot VMs only.

    main.run_simulation gives EVERY spot VM in the pool its own Poisson
    hibernation/resume chain from t = 0 (lambda_h = kh/D, lambda_r = kr/D),
    whether or not the scheduler ever launches it. TCC23 hibernates running
    instances; its Table 9 counts grow with the job (sc2, kh = 5: 3.33
    hibernations per J60 run, 8.00 per ED200 run), which a pool-wide process
    of fixed size cannot produce and a per-job reading (at most kh) cannot
    either.

    Here a spot VM launched by the scheduler's primary schedule (in
    _launches at the moment the engine starts) keeps main.py's chain
    VERBATIM, so every run in which no never-launched VM was ever hit is
    unchanged. Every other pool spot VM loses its t = 0 chain and is entered
    into the same process from the instant it is launched (LaunchCounter.
    commit), drawn from its own Random((seed + 1) * 7919 + pool index) so
    the draw is common to all schedulers. VMs R-BurstHADS provisions are
    untouched: ProvisioningEvent already exposes them from ready time.
    """
    import random
    from simulation.event_engine import EventEngine
    from simulation.events import HibernationEvent
    import models.limits as lim
    orig_run = EventEngine.run
    orig_commit = lim.LaunchCounter.commit

    def chain(vm, t0, sched, rng, engine):
        kh, kr, D = _T9["kh"], _T9["kr"], sched.D
        lam_h = kh / D
        lam_r = (kr / D) if kr else 0.0
        t = t0 + rng.expovariate(lam_h)
        while t < D:
            if lam_r > 0:
                back = t + rng.expovariate(lam_r)
                res = back if back < D else None
            else:
                res = None
            engine.add_event(HibernationEvent(t, vm, sched, resume_time=res))
            if res is None:
                break
            t = res + rng.expovariate(lam_h)

    def run(self):
        sched = self.scheduler
        launches = getattr(sched, "_launches", None)
        if _T9.get("kh") is not None and launches is not None:
            provisioned = {v.id for v in getattr(sched, "provisioned_vms", [])}
            pool = [v for v in sched.vms if v.is_spot and v.id not in provisioned]
            late = {v.id: i for i, v in enumerate(pool) if v.id not in launches._ids}
            self.events = [e for e in self.events
                           if not (isinstance(e, HibernationEvent) and e.vm.id in late)]
            _T9.update(engine=self, launches=launches, late=late, sched=sched)
        return orig_run(self)

    def commit(self, vm):
        late = _T9.get("late")
        if late and self is _T9.get("launches") and vm.id in late and vm.id not in self._ids:
            idx = late.pop(vm.id)
            rng = random.Random(((_T9.get("seed") or 0) + 1) * 7919 + idx)
            engine = _T9["engine"]
            chain(vm, engine.time, _T9["sched"], rng, engine)
        return orig_commit(self, vm)

    def apply_patch():
        _patch(EventEngine, "run", run)
        _patch(lim.LaunchCounter, "commit", commit)
    return apply_patch


def _launch_billing():
    """B1: bill every VM from its launch (TCC23 section 3.1: "When a new vmj
    is launched, the user is charged cj for each period of time").

    On disk, billing opens at a VM's first task (VM.start_next_if_free), so a
    launched VM that never runs a task costs nothing. Here LaunchCounter.
    commit, the single point where every scheduler launches a VM, opens the
    billing interval at the engine clock (0 before the engine starts, i.e.
    the primary schedule). start_billing is idempotent, so later dispatch
    changes nothing. Side effect, faithful to the paper: a launched VM is
    now `is_deployed`, so start_execution gives an idle one an Allocation
    Cycle."""
    from simulation.event_engine import EventEngine
    import models.limits as lim
    orig_run, orig_commit = EventEngine.run, lim.LaunchCounter.commit

    def run(self):
        _T9["billing_engine"] = self
        return orig_run(self)

    def commit(self, vm):
        if vm.id not in self._ids:
            eng = _T9.get("billing_engine")
            vm.start_billing(float(eng.time) if eng is not None else 0.0)
        return orig_commit(self, vm)

    def apply_patch():
        _patch(EventEngine, "run", run)
        _patch(lim.LaunchCounter, "commit", commit)
    return apply_patch


def _ac_cycles(counted):
    """E10: where an idle VM's Allocation Cycle ends.

    counted=False reproduces VM.start_ac on disk through the same patch
    point: a fresh 900 s from the moment the VM goes idle. Exists to prove
    the patch is faithful.
    counted=True follows TCC23 section 3.3 ("the allocation time is logically
    divided into units denoted Allocation Cycles (ACs). A vmj that reaches
    the end of its current AC ... in idle state, is terminated") and the
    reference Dispatcher.next_period_end: periods = ceil(uptime / AC), end =
    start_time + periods * AC + hibernated time, uptime excluding
    hibernation. Billed seconds are exactly that uptime (billing stops on
    hibernation), so the current cycle ends at now + ceil(u/AC)*AC - u, one
    period at least."""
    import math
    from models.vm import VM

    def start_ac(self, current_time):
        if not counted:
            self.current_ac_start = current_time
            self.ac_termination_time = current_time + self.allocation_cycle
            return
        ac = self.allocation_cycle
        u = self.billed_seconds(current_time)
        periods = max(1, math.ceil(u / ac - 1e-9))
        self.current_ac_start = current_time - (u - (periods - 1) * ac)
        self.ac_termination_time = current_time + (periods * ac - u)

    return lambda: _patch(VM, "start_ac", start_ac)


# Round A closing grid: guard (U5) on/off x Allocation Cycle boundaries (E10)
# off/on, on the state Round B adopts (migration fix U6/H2, billing from launch
# B1). "nocap+" = validation catalogue setting, bare = capped sweep setting.
_GRID = {
    "g1e0": [],
    "g0e0": [_burst_fill(False)],
    "g1e1": [_ac_cycles(True)],
    "g0e1": [_burst_fill(False), _ac_cycles(True)],
}


def _grid_variants():
    out = {}
    for cell, extra in _GRID.items():
        core = [lambda: _migrate_to_launched(True)(), lambda: _launch_billing()()] + list(extra)
        out[f"grid_{cell}"] = core
        out[f"nocap+grid_{cell}"] = [lambda: _nocap()()] + core
    return out


VARIANTS = {
    "base":             [],
    "nocap+ac_copy":         [lambda: _nocap()(), _ac_cycles(False)],
    "nocap+mig_launched+launch_bill": [lambda: _nocap()(), lambda: _migrate_to_launched(True)(),
                                       lambda: _launch_billing()()],
    **_grid_variants(),
    "nocap+t9_deployed":     [lambda: _nocap()(), lambda: _t9_deployed()()],
    "nocap+mig_launched+t9_deployed": [lambda: _nocap()(), lambda: _migrate_to_launched(True)(),
                                       lambda: _t9_deployed()()],
    "mig_launched+t9_deployed": [lambda: _migrate_to_launched(True)(), lambda: _t9_deployed()()],
    "nocap+no_release":      [lambda: _nocap()(), lambda: _no_release()()],
    "nocap":                 [lambda: _nocap()()],
    "mig_launched":          [lambda: _migrate_to_launched(True)()],
    "mig_copy":              [lambda: _migrate_to_launched(False)()],
    "nocap+mig_copy":        [lambda: _nocap()(), lambda: _migrate_to_launched(False)()],
    "nocap+mig_launched":    [lambda: _nocap()(), lambda: _migrate_to_launched(True)()],
    "nocap+fill_copy":       [lambda: _nocap()(), _burst_fill(True)],
    "nocap+burst_fill":      [lambda: _nocap()(), _burst_fill(False)],
    "nocap+mig_launched+burst_fill": [lambda: _nocap()(),
                                      lambda: _migrate_to_launched(True)(),
                                      _burst_fill(False)],
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


def apply(name, kh=None, kr=None, seed=None):
    if name not in VARIANTS:
        raise ValueError(f"unknown variant {name!r}; have {sorted(VARIANTS)}")
    _restore_all()
    _T9.clear()
    _T9.update(kh=kh, kr=kr, seed=seed)
    for fn in VARIANTS[name]:
        fn()
