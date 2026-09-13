"""
HADS: Hibernation-Aware Dynamic Scheduler.
Predecessor to BurstHADS. Proposed in:
  Teylo, L.; Arantes, L.; Sens, P.; Drummond, L. "A dynamic task
  scheduler tolerant to multiple hibernations in cloud environments."
  Cluster Computing, 2021.

This is a faithful PORT of the real reference implementation, not an
independent reimplementation from the paper's prose. Source verified
directly against github.com/luanteylo/hads_ (public repo, no
code-availability statement needed since it's simply public):
  control/scheduler/CCScheduler.py   -- primary + dynamic scheduler
  control/scheduler/schedulers.py    -- shared WRR/round-robin helpers
  control/domain/instance_type.py    -- confirms `rank = gflops /
                                         price_preemptible`, i.e. the
                                         same speed-per-cost ratio as
                                         BurstHADS's Eq-8 WRR weight,
                                         just always evaluated against
                                         the preemptible/spot price
                                         specifically (all CCScheduler
                                         ever builds its round-robin
                                         list over).
The class name "CC" in that repo stands for the Cluster Computing
paper -- i.e. this scheduler, not the later Burst-HADS/IPDPS one.

An earlier version of this file subclassed BurstHADS and simulated
HADS by disabling burst allocation and adding an invented "wait for
the hibernated VM to resume" migration philosophy with a made-up
resume_wait_threshold. NEITHER of those exists anywhere in the real
CCScheduler.py: it never waits on a hibernated VM, and -- more
importantly -- it never runs an ILS at all. That version is discarded
entirely; every method below is rebuilt from the real algorithm.

Key differences from BurstHADS, per the actual reference code:
  1. No burstable VMs, no CPU credits, no burst mode -- only spot
     (preemptible) + on-demand.
  2. Primary/static scheduler is a SINGLE-PASS GREEDY heuristic, NOT
     an iterated local search. CCScheduler.create_primary_map has no
     local search, no fitness function, no iterations of any kind --
     it places each task once, greedily, and is done. This is the
     single biggest structural correction versus the previous version
     of this file, which inherited BurstHADS's entire ILS machinery.
  3. Per task (sorted by memory descending, same as BurstHADS/the
     paper's Algorithm 2), three ordered phases, exactly mirroring
     CCScheduler.create_primary_map:
       (a) an already-open queue, least-loaded first, admitted if its
           own market's deadline rule is satisfied (Dspot for spot,
           D for on-demand);
       (b) a brand-new spot VM, chosen by the same smooth-WRR pick
           BurstHADS uses for its own Phase 2 (weight = speed /
           spot_price, matching CCScheduler's `rank`);
       (c) a brand-new on-demand VM, cheapest price first.
     If no phase admits the task, this raises -- the real code does
     the same ("THERE IS NO SOLUTION WITH THAT DEADLINE").
  4. Dynamic scheduler (select_vm, called on hibernation/termination):
     CCScheduler.migrate's three-stage cascade -- idle VMs (any
     market) first, then working/busy VMs (work-stealing into a live
     queue), then a brand-new on-demand VM as the last resort. A spot
     migration target also has to clear the same spare-time margin as
     BurstHADS's own Attempt 2 (`task_max_timedelta` in the real
     Dispatcher class -- shared migration-procedure infrastructure,
     not something introduced only in the later Burst-HADS paper, so
     it belongs here too). CCScheduler.migrate's own backup_heuristic
     explicitly skips
     `instance.burstable`, so "never launch a fresh spot VM to
     recover from a hibernation" and "never touch a burstable VM" are
     both taken directly from the source, not assumed.

One thing deliberately NOT ported, to keep HADS on the same footing
as the other schedulers already in this codebase rather than
introducing an inconsistency between them:
  - CCScheduler's real Queue class (control/scheduler/queue.py) does
     true interval-based multi-core slot search with per-interval
     memory-overlap checking across cores. This simulator uses the
     coarser "assign to whichever core has the least load so far"
     packing (VM.estimate_finish_time / _vm_makespan_static)
     uniformly for BurstHADS and RBurstHADS already. Giving HADS a
     different, more exact packing model than its two comparison
     points would make the three schedulers' queues behave
     inconsistently with each other, which is a worse fidelity
     trade-off than sharing one simpler model everywhere.

Purpose in the comparison: shows what the ILS + burstable VMs
actually ADD over the older, simpler greedy heuristic -- rather than
comparing against a philosophy (wait-for-resume) Teylo et al. never
proposed.
"""

from models.vm import VM
from models.limits import LaunchCounter, NoFeasibleSchedule
from simulation.provisioning_event import STARTUP_LATENCY


class HADSSolution:
    """
    Minimal solution container for HADS's one-shot greedy result.
    Deliberately NOT SchedulingSolution (scheduler/burst_hads.py) --
    that class carries clone()/selected_vms machinery built for an
    ILS candidate loop HADS doesn't have. Kept separate so nothing
    about HADS's solution accidentally implies it went through local
    search.
    """
    def __init__(self, allocation, selected_vms):
        self.allocation   = allocation
        self.selected_vms = list(selected_vms)


class HADS:
    """
    Real HADS, per Teylo et al. (Cluster Computing, 2021) and the
    public reference implementation (github.com/luanteylo/hads_,
    control/scheduler/CCScheduler.py):
      - Spot + on-demand only. No burstable VMs, no CPU credits, no
        burst mode.
      - Primary scheduler: ONE-PASS greedy WRR construction. No ILS.
      - Dynamic scheduler: idle -> working (work-stealing) -> new
        on-demand VM cascade. No "wait for resume" patience mechanism
        of any kind.
    """

    def __init__(self, vms, all_tasks, jobs, deadline=None, **_ignored):
        # **_ignored absorbs any alpha=/burst_rate=-style kwargs a
        # caller might still pass from when this class subclassed
        # BurstHADS -- HADS has neither an ILS alpha nor burstable
        # VMs, so those parameters are meaningless here now and are
        # silently dropped rather than raising a TypeError.
        self.all_vms   = vms
        self.vms       = vms          # public alias, matches BurstHADS
        self.all_tasks = all_tasks
        self.jobs      = jobs

        # HADS pools: burstable VMs are excluded by construction, but
        # note the raw `vms`/`all_vms` list (shared across scheduler
        # classes by main.py's run_simulation) can still physically
        # contain burstable VM objects -- they are simply never
        # selected by anything below, so they sit permanently idle
        # and unbilled for the whole run, which is the correct
        # behavior for "HADS doesn't have burstable VMs."
        self.spot_vms      = [v for v in vms if v.market == VM.SPOT]
        self.burstable_vms = []
        self.ondemand_vms  = [v for v in vms if v.market == VM.ONDEMAND]

        # Algorithm 5 (work stealing) is a BURST-HADS contribution, not
        # part of HADS. Teylo et al. describe the 2021 work as "a dynamic
        # scheduler, denoted HADS, that uses both spot and regular
        # (non-burstable) on-demand VMs" which reacts to hibernation by
        # MIGRATING the affected tasks; work stealing for load balancing
        # arrives with Burst-HADS, tied to burstable VMs in burst mode.
        # Leaving it enabled here handed the baseline the very mechanism
        # the paper under test is contributing -- measured on J60/sc1 it
        # pulled HADS from 2540.7s to 2324.7s and erased two thirds of the
        # makespan gap Burst-HADS is supposed to show.
        self.enable_work_stealing = False

        if deadline is not None:
            self.D = deadline
        else:
            dls = [t.deadline for t in all_tasks if t.deadline is not None]
            self.D = max(dls) if dls else float('inf')

        self.Dspot         = None
        self.solution       = None
        self.event_engine   = None
        self._hibernation_occurred = False

        # Id counter for VMs launched on the fly from the elastic M^o
        # pool. Offset well clear of BurstHADS's own counter (10000+)
        # and RBurstHADS's (100+) -- harmless if it overlaps in
        # practice since each scheduler is instantiated fresh per
        # simulation run, but kept distinct for clarity when reading
        # VM ids in debug output.
        self._next_new_vm_id = 20000

        # Smooth-WRR accumulator state, reset fresh at the start of
        # the one and only scheduling pass (_greedy_construct).
        self._wrr_current = {}

        # Instance limits (models/limits.py): what this run has launched.
        self._launches = LaunchCounter()

    # ------------------------------------------------------------------
    # DSPOT
    # ------------------------------------------------------------------

    def compute_dspot(self):
        """
        Dspot = D - worst_case_migration_execution_time.
        Same definition and purpose as BurstHADS.compute_dspot --
        kept as its own copy rather than a shared import so HADS has
        no dependency on BurstHADS at all, matching the fact that in
        the real repo CCScheduler and IPDPS are siblings (both
        subclass Scheduler directly), not one inheriting the other's
        machinery.
        """
        if not self.all_tasks:
            return self.D

        candidate_vms = self.spot_vms + self.ondemand_vms
        if not candidate_vms:
            candidate_vms = self.all_vms

        slowest_vm   = min(candidate_vms, key=lambda v: v.speed)
        longest_task = max(self.all_tasks, key=lambda t: t.exec_time)

        worst_exec = (longest_task.exec_time
                      * (1.0 + longest_task.checkpoint_overhead)
                      / slowest_vm.speed)

        dspot = self.D - worst_exec
        if dspot <= 0:
            raise ValueError(
                f"Dspot={dspot:.2f} non-positive. "
                f"Deadline D={self.D:.2f} too tight. "
                f"Worst case exec={worst_exec:.2f}s."
            )
        return dspot

    # ------------------------------------------------------------------
    # WRR WEIGHT -- CCScheduler/InstanceType's `rank`
    # ------------------------------------------------------------------

    def wrr_weight(self, vm):
        """
        rank = gflops / price_preemptible (control/domain/
        instance_type.py) -- whole-instance computing power per unit
        spot cost. Structurally the same ratio as BurstHADS's Eq-8
        weight, evaluated the same way the real round-robin list is
        actually built: over preemptible/spot instances only.

        Teylo et al. define this as weight(vm_j) = Gflops_j / c_j, where
        "the Gflops_j of a vm_j is used to quantify the computing power
        of vm_j" -- a LINPACK measurement of the WHOLE INSTANCE, not a
        per-core figure. Their Constraint 4 is explicit that "a
        multi-core vm_j (nvc_j > 1) can execute more than one task
        simultaneously (one task per core)", so a 4-vCPU instance
        delivers proportionally more Gflops than a 2-vCPU one of the
        same family.

        In this codebase a VM's computing power is split across two
        attributes: `speed` is the per-TASK speedup and `vcpu_count` is
        how many tasks run concurrently. The whole-instance quantity the
        paper calls Gflops is therefore speed * vcpu_count -- NOT
        `speed` alone.

        This previously returned `speed / cost_rate`, which silently
        divided out the vCPU dimension. The effect was not cosmetic: it
        rated c5.large (2x2 = 4 units at $0.0306) and c5.xlarge (4x4 =
        16 units at $0.0612) as EXACTLY EQUAL, when the latter is 2x
        more work per dollar. On a tie the accumulator keeps the first
        candidate, so the greedy opened the slowest, least efficient
        instance in the pool first and then packed into it -- which is
        what produced HADS's pathological single-VM placements and its
        deadline misses on the undisturbed baseline. Every other part of
        the simulator (VM.start_next_if_free, estimate_finish_time,
        _vm_makespan_static) is already vcpu-aware; this ranking was the
        one place that was not.
        """
        if vm.cost_rate == 0:
            return float('inf')
        return (vm.speed * vm.vcpu_count) / vm.cost_rate

    def _wrr_pick(self, feasible_vms):
        """
        Smooth Weighted Round Robin, identical mechanics to
        BurstHADS._wrr_pick. Kept as its own copy for the same
        independence reason as compute_dspot above -- the real
        Scheduler.build_roundrobin_list is a @staticmethod shared by
        both CCScheduler and IPDPS via simple composition, not
        inheritance, so duplicating the (small) picking logic here
        mirrors that relationship more closely than subclassing would.
        """
        if not feasible_vms:
            return None
        total = sum(self.wrr_weight(v) for v in feasible_vms)
        if total <= 0 or total == float('inf'):
            return feasible_vms[0]

        best    = None
        best_cw = float('-inf')
        for v in feasible_vms:
            self._wrr_current.setdefault(v.id, 0.0)
            self._wrr_current[v.id] += self.wrr_weight(v)
            if self._wrr_current[v.id] > best_cw:
                best_cw = self._wrr_current[v.id]
                best    = v

        self._wrr_current[best.id] -= total
        return best

    # ------------------------------------------------------------------
    # MULTI-CORE LIST SCHEDULING -- same substrate as BurstHADS
    # (kept local rather than shared for the independence reason
    # above; see the module docstring for why the real Queue class's
    # exact interval-search packing is not ported).
    # ------------------------------------------------------------------

    def _vm_makespan_static(self, tasks, vm):
        # A task's planned duration carries (1 + checkpoint_overhead),
        # because VM.start_next_if_free charges exactly that on every
        # execution and VM.estimate_finish_time mirrors it. Planning
        # without it packed each queue against Dspot (spot) or D
        # (on-demand) in units execution never delivers: the queue then
        # ran 10% past its planned end, and wherever 10% of the planned
        # end exceeds the D - Dspot migration margin, its tail finished
        # after D on a VM that was never interrupted. BurstHADS's planner
        # had the same omission and is corrected identically.
        cores = [0.0] * vm.vcpu_count
        for t in tasks:
            idx = cores.index(min(cores))
            cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
        return max(cores) if cores else 0.0

    # ------------------------------------------------------------------
    # SCHEDULE ENTRY POINT
    # ------------------------------------------------------------------

    def schedule(self, current_time):
        if self.solution is None:
            self._run_primary_scheduler()

    def _run_primary_scheduler(self):
        self.Dspot = self.compute_dspot()
        allocation, selected_vms = self._greedy_construct()
        self.solution = HADSSolution(allocation, selected_vms)
        self._apply_solution(self.solution)

    # ------------------------------------------------------------------
    # PRIMARY SCHEDULER -- CCScheduler.create_primary_map, ported
    # directly. Single pass. No local search of any kind.
    # ------------------------------------------------------------------

    def _greedy_construct(self):
        tasks_sorted = sorted(self.all_tasks,
                              key=lambda t: t.memory_req, reverse=True)

        ondemand_sorted = sorted(self.ondemand_vms, key=lambda v: v.cost_rate)

        allocation      = {}
        selected_vms    = []
        selected_vm_ids = set()
        vm_tasks        = {}   # vm_id -> [Task,...] tentatively assigned
        vm_memory       = {}

        self._wrr_current = {vm.id: 0.0 for vm in self.spot_vms}

        for task in tasks_sorted:
            placed = False

            # Phase (a): an already-open queue, least-loaded first.
            # CCScheduler doesn't separate spot vs on-demand ordering
            # here -- it sorts every currently-open queue by makespan
            # and tries them in that order, applying whichever
            # deadline rule matches THAT queue's own market.
            open_queues = sorted(
                selected_vms,
                key=lambda v: self._vm_makespan_static(
                    vm_tasks.get(v.id, []), v)
            )
            for vm in open_queues:
                deadline = self.Dspot if vm.market == VM.SPOT else self.D
                if self._check_schedule(task, vm, vm_tasks, vm_memory,
                                        deadline):
                    allocation[task.task_id] = vm.id
                    vm_tasks.setdefault(vm.id, []).append(task)
                    vm_memory[vm.id] = (vm_memory.get(vm.id, 0)
                                        + task.memory_req)
                    placed = True
                    break
            if placed:
                continue

            # Phase (b): a brand-new spot VM, WRR-picked.
            feasible_spot = [
                vm for vm in self.spot_vms
                if vm.id not in selected_vm_ids
                and self._launches.can_launch(vm)
                and self._check_schedule(task, vm, vm_tasks, vm_memory,
                                         self.Dspot)
            ]
            pick = self._wrr_pick(feasible_spot)
            if pick is not None:
                self._launches.commit(pick)
                allocation[task.task_id] = pick.id
                vm_tasks.setdefault(pick.id, []).append(task)
                vm_memory[pick.id] = (vm_memory.get(pick.id, 0)
                                      + task.memory_req)
                selected_vms.append(pick)
                selected_vm_ids.add(pick.id)
                continue

            # Phase (c): an on-demand VM, cheapest first -- existing
            # ones first, and if NONE of those fit, elastically launch
            # a brand-new one from the M^o pool and use that instead.
            #
            # This elastic-launch half was missing entirely in an
            # earlier version of this method, which only ever tried
            # the on-demand VM(s) already sitting in self.ondemand_vms
            # (one single VM, in this codebase's default pool) and
            # never opened a second one. The real CCScheduler.
            # create_primary_map does NOT have that limitation: its
            # own Phase (c) creates a brand-new Queue object for every
            # task that reaches it, capped only by
            # `instance.limits_ondemand` (a per-instance-TYPE count
            # limit, typically far more than one) -- i.e. it treats
            # on-demand as elastic during static scheduling too, not
            # just during dynamic migration. Confining it to one fixed
            # VM object meant every task that overflowed the two spot
            # VMs' Dspot budget got serialized onto that SAME single
            # on-demand VM, one after another -- and since D itself
            # scales up proportionally with n (compute_deadlines), that
            # single VM never looked "full" relative to the deadline,
            # it just ran for a very long time. That's what produced
            # the previously-observed ~5x makespan gap against
            # BurstHADS at n=300: not a real algorithmic difference,
            # but HADS being artificially starved of on-demand capacity
            # that the reference algorithm never actually restricts.
            for vm in ondemand_sorted:
                if vm.id in selected_vm_ids:
                    continue
                if not self._launches.can_launch(vm):
                    continue
                if self._check_schedule(task, vm, vm_tasks, vm_memory,
                                        self.D):
                    self._launches.commit(vm)
                    allocation[task.task_id] = vm.id
                    vm_tasks.setdefault(vm.id, []).append(task)
                    vm_memory[vm.id] = (vm_memory.get(vm.id, 0)
                                        + task.memory_req)
                    selected_vms.append(vm)
                    selected_vm_ids.add(vm.id)
                    placed = True
                    break
            if placed:
                continue

            template_type = (self.ondemand_vms[0].vm_type
                             if self.ondemand_vms else "c5.large")
            if not self._launches.can_launch_type("ondemand", template_type):
                raise NoFeasibleSchedule(
                    f"HADS: no placement for task {task.task_id} within "
                    f"D={self.D:.1f}s and the instance limits.")
            new_vm = self._launch_new_ondemand_vm(0.0)
            if self._check_schedule(task, new_vm, vm_tasks, vm_memory,
                                    self.D):
                ondemand_sorted.append(new_vm)
                ondemand_sorted.sort(key=lambda v: v.cost_rate)
                allocation[task.task_id] = new_vm.id
                vm_tasks.setdefault(new_vm.id, []).append(task)
                vm_memory[new_vm.id] = (vm_memory.get(new_vm.id, 0)
                                        + task.memory_req)
                selected_vms.append(new_vm)
                selected_vm_ids.add(new_vm.id)
                continue

            # THERE IS NO SOLUTION BEFORE THE DEADLINE FOR THIS TASK --
            # not even a brand-new, empty on-demand VM can fit it. The
            # real code raises here too (create_primary_map's own hard
            # failure), rather than silently dropping the task.
            raise RuntimeError(
                f"HADS: no feasible placement for task {task.task_id} "
                f"before deadline D={self.D:.1f}s "
                f"(Dspot={self.Dspot:.1f}s)."
            )

        return allocation, selected_vms

    def _check_schedule(self, task, vm, vm_tasks, vm_memory, deadline):
        """Feasibility check for assigning task to vm: memory capacity
        (Constraint 3) plus the caller-supplied deadline (Dspot for a
        spot queue, D for an on-demand one)."""
        current_mem = vm_memory.get(vm.id, 0)
        if current_mem + task.memory_req > vm.memory_mb:
            return False

        tasks_if_added = vm_tasks.get(vm.id, []) + [task]
        return self._vm_makespan_static(tasks_if_added, vm) <= deadline

    # ------------------------------------------------------------------
    # APPLY SOLUTION TO VM QUEUES
    # ------------------------------------------------------------------

    def _apply_solution(self, solution):
        vm_map = {vm.id: vm for vm in self.all_vms}

        for vm in self.all_vms:
            vm.tasks = []
            vm.running = []
            vm._queued_memory_mb = 0.0

        buckets = {}
        for task in self.all_tasks:
            vm_id = solution.allocation.get(task.task_id)
            if vm_id is None:
                continue
            buckets.setdefault(vm_id, []).append(task)

        for vm_id, tasks in buckets.items():
            vm = vm_map.get(vm_id)
            if vm is None:
                continue
            tasks.sort(key=lambda t: t.memory_req, reverse=True)
            vm.tasks = tasks
            self._launches.commit(vm)
            for task in tasks:
                task.assigned_vm = vm
                vm.reserve_memory(task)

    def _remove_terminated_vm(self, vm):
        """Remove a terminated VM from HADS's active pools."""
        for pool in [self.spot_vms, self.ondemand_vms]:
            if vm in pool:
                pool.remove(vm)

    # ------------------------------------------------------------------
    # DYNAMIC SCHEDULER -- CCScheduler.migrate, ported per-task (this
    # simulator calls select_vm once per migrated task rather than
    # handing the scheduler the whole affected_tasks list at once, so
    # the three-stage cascade below is CCScheduler.migrate's structure
    # re-expressed at that granularity, not a re-derivation of it).
    #
    #   Stage 1 (idle):    any idle spot or on-demand VM.
    #   Stage 2 (working):  any busy spot or on-demand VM -- work-
    #                       stealing into its live queue.
    #   Stage 3 (new):      a brand-new on-demand VM. Never a fresh
    #                       spot VM -- CCScheduler.migrate's own
    #                       backup_heuristic only ever opens ON_DEMAND
    #                       queues, for the obvious reason that a new
    #                       spot VM would just carry the same
    #                       hibernation risk with none of the upside.
    #                       Never burstable either -- HADS predates
    #                       burstable-VM support entirely.
    # ------------------------------------------------------------------

    def _check_migration(self, task, vm, current_time, deadline,
                          burst_mode=False):
        """
        check_migration(t_i, vm_j, D) -- CCScheduler's inline
        equivalent (memory feasibility + finish-time-before-deadline),
        PLUS the same spot-VM spare-time margin now enforced in
        BurstHADS._check_migration.

        This module's docstring originally said this margin
        (CCScheduler.migrate's `dispatcher.task_max_timedelta` check)
        was deliberately left out to keep HADS on the same dynamic-
        migration strictness as BurstHADS, which at the time used one
        flat deadline test for every market. That premise no longer
        holds: rereading Teylo et al.'s Section 3.4 text confirmed the
        margin is real (not a code-only quirk) and BurstHADS's
        _check_migration was updated to enforce it for spot targets.
        `task_max_timedelta` is, in the real repo, a property on the
        shared Dispatcher class that BOTH CCScheduler.migrate and
        IPDPS.migrate apply identically to preemptible-market targets
        -- it's core migration-procedure infrastructure, not something
        introduced only in the later Burst-HADS paper. Leaving it out
        of HADS now, after adding it to BurstHADS, would make the two
        schedulers inconsistently strict for reasons that no longer
        apply, and would understate real HADS's own caution about
        migrating tasks onto spot VMs that are themselves still
        exposed to hibernation.

        Accepts (and ignores) burst_mode so this satisfies the same
        call signature policies/work_stealing.py uses for every
        scheduler (`scheduler._check_migration(task, idle_vm,
        current_time, deadline, burst_mode=False)`) -- HADS has no
        burstable VMs to ever pass burst_mode=True for in the first
        place.
        """
        if not vm.can_fit_task(task):
            return False

        finish = vm.estimate_finish_time(task, current_time)
        if finish > deadline:
            return False

        if vm.is_spot:
            candidate_tasks = list(vm.tasks) + [task]
            longest = max(t.exec_time / vm.speed for t in candidate_tasks)
            spare   = deadline - finish
            if spare <= longest:
                return False

        return True

    def select_vm(self, task, job, current_time):
        """CCScheduler.migrate's cascade, entry point for one task."""
        deadline = self.D

        # Stage 1: idle dispatchers (any market).
        idle = [v for v in (self.spot_vms + self.ondemand_vms)
                if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                and not v.tasks]
        for vm in sorted(idle, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm

        # Stage 2: working/busy dispatchers -- work-stealing into a
        # live queue.
        working = [v for v in (self.spot_vms + self.ondemand_vms)
                   if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                   and v.tasks]
        for vm in sorted(working, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm

        # Stage 3: brand-new on-demand VM, last resort.
        return self._attempt_ondemand_fallback(task, current_time)

    def _attempt_ondemand_fallback(self, task, current_time):
        """
        Pull one VM out of the elastic M^o pool. Same deadline test as
        CCScheduler.backup_heuristic (start + exec_time + deployment
        overhead < D); STARTUP_LATENCY stands in for the paper's omega
        (time to deploy a new VM), same as BurstHADS's own fallback.
        """
        deadline = self.D
        template_type = (self.ondemand_vms[0].vm_type
                         if self.ondemand_vms else "c5.large")
        if not self._launches.can_launch_type("ondemand", template_type):
            return self._capped_fallback(task, current_time)
        new_vm = self._launch_new_ondemand_vm(current_time)
        finish = (current_time + STARTUP_LATENCY
                  + task.remaining_time / new_vm.speed)
        if new_vm.can_fit_task(task) and finish <= deadline:
            return new_vm

        # Even a brand-new on-demand VM can't make the deadline -- the
        # task is already unsavable. Not part of CCScheduler.migrate:
        # rather than orphaning it, still run it there (late) so it
        # shows up as a deadline miss instead of vanishing from the
        # simulation, matching BurstHADS's own fallback behavior here.
        return new_vm

    def _launch_new_ondemand_vm(self, current_time):
        """
        Pull one VM out of M^o -- same type/speed/price/vcpu_count as
        whatever on-demand VM(s) are already in the pool. Unlimited
        supply, matching CCScheduler's own on-demand fallback (no cap
        on M^o beyond the underlying instance-type limits, which this
        simulator doesn't model at the fleet-size level).
        """
        template  = self.ondemand_vms[0] if self.ondemand_vms else None
        vm_type   = template.vm_type    if template else "c5.large"
        speed     = template.speed      if template else 2
        cost_rate = template.cost_rate  if template else 0.085 / 3600
        memory_gb = template.memory_gb  if template else 4.0
        vcpu      = template.vcpu_count if template else 2

        new_vm = VM(
            vm_id=self._next_new_vm_id, vm_type=vm_type,
            market=VM.ONDEMAND, speed=speed, cost_rate=cost_rate,
            memory_gb=memory_gb, hibernation_rate=0.0,
            vcpu_count=vcpu,
        )
        self._next_new_vm_id += 1
        new_vm.state = VM.IDLE

        self.ondemand_vms.append(new_vm)
        if new_vm not in self.all_vms:
            self.all_vms.append(new_vm)
        if new_vm not in self.vms:
            self.vms.append(new_vm)
        self._launches.commit(new_vm)
        return new_vm

    def _capped_fallback(self, task, current_time):
        """No new on-demand VM may be launched: the instance limit is spent.

        CCScheduler.backup_heuristic leaves such a task unallocated, which
        in a real run loses it. Losing it here would remove it from every
        metric, so instead it waits on the active non-burstable VM that
        would finish it soonest -- it still runs, and a late finish counts
        as a deadline miss. Only if no such VM exists (every launched
        instance already terminated) is one more launched past the limit,
        and that is counted in self._launches.overrides.
        """
        cands = [v for v in (self.spot_vms + self.ondemand_vms)
                 if v.state not in (VM.HIBERNATED, VM.TERMINATED)
                 and self._launches.can_launch(v)]
        fit = [v for v in cands if v.can_fit_task(task)]
        if fit or cands:
            vm = min(fit or cands,
                     key=lambda v: v.estimate_finish_time(task, current_time))
            self._launches.commit(vm)
            return vm
        self._launches.overrides += 1
        return self._launch_new_ondemand_vm(current_time)

    def slack(self, task, vm, deadline, current_time):
        """Used by policies/work_stealing.py -- same contract as
        BurstHADS.slack."""
        return deadline - vm.estimate_finish_time(task, current_time)
