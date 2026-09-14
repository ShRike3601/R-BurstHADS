"""
Burst-HADS: Burst Hibernation-Aware Dynamic Scheduler
Faithful implementation of:
  Teylo et al., IEEE TCC 2023.

Updates in this version:
  - Memory-aware task scheduling (Constraint 3 from paper)
  - Tasks sorted by memory requirement descending (Algorithm 2)
  - Realistic AWS T3 CPU credit model for burstable VMs
  - Checkpoint/recovery support (remaining_time reduced on restart)
  - Termination vs hibernation distinction
  - AC-based idle VM termination support
  - Elastic on-demand fallback (Algorithm 4's M^o pool of
    "non-launched regular on-demand VMs" -- unlimited, not a single
    fixed VM)
  - Multi-core VMs (Constraint 3/4): a VM with vcpu_count > 1 can run
    that many tasks concurrently. The static scheduler (Algorithm
    2/3, Eq 9) now list-schedules a VM's assigned tasks across its
    cores instead of assuming every VM is a single sequential worker
    -- otherwise a 4-vCPU VM would still only ever get one task's
    worth of work packed onto it before the ILS considered it "full."
  - WRR (Equation 8) actually wired into Algorithm 2 Phase 2, instead
    of sitting unused while a "least loaded" heuristic ran things.
  - Proactive burstable VM allocation (Algorithm 1 Part 2) actually
    implemented, instead of being a no-op.
"""

import math
import random
import copy
from models.vm import VM
from models.catalogue import catalogue, make_vm
from models.limits import LaunchCounter, NoFeasibleSchedule
from simulation.provisioning_event import STARTUP_LATENCY


class SchedulingSolution:
    """
    One candidate scheduling map produced by the ILS.
    allocation: {task_id -> vm_id}
    selected_vms: list of VM objects chosen for this solution
    """
    def __init__(self, allocation, selected_vms):
        self.allocation   = allocation
        self.selected_vms = list(selected_vms)

    def clone(self):
        return SchedulingSolution(
            allocation=dict(self.allocation),
            selected_vms=list(self.selected_vms),
        )


class BurstHADS:
    """
    Primary scheduler: ILS + WRR + burstable allocation
    Dynamic scheduler: burst migration + work stealing
    """

    def __init__(self, vms, all_tasks, jobs,
                 deadline=None, alpha=0.5, burst_rate=0.2):
        self.all_vms   = vms
        self.vms       = vms          # public alias for event engine
        self.all_tasks = all_tasks
        self.jobs      = jobs
        self.alpha     = alpha
        self.burst_rate = burst_rate
        self.enable_work_stealing = True

        # Separate VM pools by market type
        self.spot_vms      = [v for v in vms if v.market == VM.SPOT]
        self.burstable_vms = [v for v in vms if v.market == VM.BURSTABLE]
        self.ondemand_vms  = [v for v in vms if v.market == VM.ONDEMAND]
        # M^o's and M^b's types, fixed at start (models/catalogue.py,
        # DEVIATIONS E3).
        self._od_catalogue    = catalogue(vms, VM.ONDEMAND)
        self._burst_catalogue = catalogue(vms, VM.BURSTABLE)

        # Deadline
        if deadline is not None:
            self.D = deadline
        else:
            dls = [t.deadline for t in all_tasks if t.deadline is not None]
            self.D = max(dls) if dls else float('inf')

        self.Dspot       = None
        self.solution    = None
        self.event_engine = None
        self._hibernation_occurred = False

        # Id counter for VMs launched on the fly from the elastic
        # M^o (on-demand) / M^b (burstable) pools -- Algorithm 4's
        # "non-launched regular on-demand VMs" and the equivalent
        # burstable pool implied by Algorithm 1 Part 2. Offset well
        # clear of the pool's own ids and of RBurstHADS's own
        # provisioning counter (which starts at 100).
        self._next_new_vm_id = 10000

        # Smooth-WRR accumulator state (Eq 8), reset fresh at the
        # start of each _initial_solution() pass.
        self._wrr_current = {}

        # Instance limits (models/limits.py): what this run has launched.
        self._launches = LaunchCounter()

    # ------------------------------------------------------------------
    # DSPOT
    # ------------------------------------------------------------------

    def compute_dspot(self):
        """
        Dspot = D - worst_case_migration_execution_time
        Worst case: longest task on slowest non-burstable VM.
        """
        if not self.all_tasks:
            return self.D

        candidate_vms = self.spot_vms + self.ondemand_vms
        if not candidate_vms:
            candidate_vms = self.all_vms

        slowest_vm   = min(candidate_vms, key=lambda v: v.speed)
        longest_task = max(self.all_tasks, key=lambda t: t.exec_time)

        # Include checkpoint overhead in worst-case estimate
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
    # WRR WEIGHT  (Equation 8)
    # ------------------------------------------------------------------

    def wrr_weight(self, vm):
        """
        Equation 8: weight(vm) = Gflops / cost_per_period.

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
        Smooth Weighted Round Robin (the classic algorithm behind
        the paper's own citation for WRR, Katevenis et al.): every
        call, each candidate's running "current weight" increases by
        its Eq-8 weight; whichever has the highest current weight
        wins and gets debited by the total. Over repeated calls this
        visits every VM roughly in proportion to its weight, instead
        of a plain "always pick the best one" rule that would just
        pile every task onto whichever single VM looks best right
        now.

        Restricted to whichever VMs are actually feasible for the
        CURRENT task (Dspot/memory permitting) -- a necessary
        adaptation, since pure WRR assumes every server is always
        available and this pool isn't. State still accumulates
        across calls for VMs that keep coming up feasible, so the
        proportional-visit property is preserved for them.
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
    # MULTI-CORE LIST SCHEDULING (Constraint 4)
    # ------------------------------------------------------------------

    def _vm_makespan_static(self, tasks, vm):
        """
        List-schedule `tasks` across vm.vcpu_count cores at vm.speed
        and return the finish time of the last core to free up --
        i.e. this VM's own makespan if it ran exactly this task set.
        This is the static-scheduling-time equivalent of
        VM.estimate_finish_time(): it's what makes the ILS actually
        pack multiple tasks onto one multi-core VM concurrently
        instead of treating every VM, no matter how many vCPUs it
        has, as a single sequential worker.

        Each task's planned duration carries (1 + checkpoint_overhead).
        VM.start_next_if_free charges that factor on every execution and
        VM.estimate_finish_time mirrors it; a planner that leaves it out
        judges Dspot and D in units execution never delivers, so every
        queue it packs runs 10% past its planned end. HADS's planner had
        the same omission and is corrected identically.
        """
        cores = [0.0] * vm.vcpu_count
        for t in tasks:
            idx = cores.index(min(cores))
            cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
        return max(cores) if cores else 0.0

    def _solution_task_finish_times(self, solution):
        """
        {task: predicted finish time} for every task in `solution`,
        via the same list-scheduling model as _vm_makespan_static but
        keeping each task's own finish time instead of collapsing to
        the VM's overall makespan. Used by proactive burst allocation
        to find which tasks are projected to blow Dspot. Carries the
        checkpoint overhead for the same reason _vm_makespan_static
        does, and so that it is comparable with _baseline_finish, which
        always did.
        """
        vm_map  = {vm.id: vm for vm in self.all_vms}
        buckets = {}
        for task in self.all_tasks:
            vid = solution.allocation.get(task.task_id)
            if vid is None:
                continue
            buckets.setdefault(vid, []).append(task)

        finish = {}
        for vid, tasks in buckets.items():
            vm = vm_map.get(vid)
            if vm is None:
                continue
            # Execution order, for the reason given in _compute_vm_load.
            tasks.sort(key=lambda t: t.memory_req, reverse=True)
            cores = [0.0] * vm.vcpu_count
            for t in tasks:
                idx = cores.index(min(cores))
                cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
                finish[t] = cores[idx]
        return finish

    # ------------------------------------------------------------------
    # SCHEDULE ENTRY POINT
    # ------------------------------------------------------------------

    def schedule(self, current_time):
        if self.solution is None:
            self._run_primary_scheduler()

    def _run_primary_scheduler(self):
        self.Dspot = self.compute_dspot()
        initial    = self._initial_solution()
        if initial is None:
            raise RuntimeError("No feasible initial solution.")
        best   = self._iterated_local_search(initial)
        final  = self._allocate_burstable_vms(best)
        self.solution = final
        self._apply_solution(final)

    # ------------------------------------------------------------------
    # ALGORITHM 2 — GREEDY INITIAL SOLUTION
    # ------------------------------------------------------------------

    def _initial_solution(self):
        """
        Greedy initial solution (paper Algorithm 2).
        Phase 1: least-loaded already-selected spot VM.
        Phase 2: WRR-selected (Eq 8) spot VM among those still
                 feasible for this task -- not "least loaded," which
                 left WRR entirely unused.
        On-demand VMs are NEVER in phases 1 or 2.
        """
        tasks_sorted = sorted(self.all_tasks,
                              key=lambda t: t.memory_req, reverse=True)

        spot_pool = self.spot_vms
        if not spot_pool:
            return None

        allocation      = {}
        selected_vms    = []
        selected_vm_ids = set()
        vm_tasks        = {}   # vm_id -> [Task,...] tentatively assigned
        vm_memory       = {}

        # Fresh smooth-WRR accumulator state for this scheduling pass.
        self._wrr_current = {vm.id: 0.0 for vm in spot_pool}

        for task in tasks_sorted:
            scheduled = False

            # Phase 1: any already-selected spot VM with room, least
            # loaded first among those (the paper's pseudocode only
            # mentions WRR for picking the NEXT new VM to select in
            # Phase 2 -- reusing an already-launched VM is a plain
            # load-balance choice).
            already_selected = sorted(
                selected_vms,
                key=lambda v: self._vm_makespan_static(
                    vm_tasks.get(v.id, []), v)
            )
            for vm in already_selected:
                if self._check_schedule(task, vm, vm_tasks, vm_memory,
                                        self.Dspot):
                    allocation[task.task_id] = vm.id
                    vm_tasks.setdefault(vm.id, []).append(task)
                    vm_memory[vm.id] = (vm_memory.get(vm.id, 0)
                                        + task.memory_req)
                    scheduled = True
                    break

            if scheduled:
                continue

            # Phase 2: WRR-selected spot VM (Eq 8) among those still
            # feasible for this task.
            feasible = [
                vm for vm in spot_pool
                if self._launches.can_launch(vm)
                and self._check_schedule(task, vm, vm_tasks, vm_memory,
                                        self.Dspot)
            ]
            best_vm = self._wrr_pick(feasible)

            if best_vm is not None:
                self._launches.commit(best_vm)
                allocation[task.task_id] = best_vm.id
                vm_tasks.setdefault(best_vm.id, []).append(task)
                vm_memory[best_vm.id] = (vm_memory.get(best_vm.id, 0)
                                         + task.memory_req)
                if best_vm.id not in selected_vm_ids:
                    selected_vms.append(best_vm)
                    selected_vm_ids.add(best_vm.id)
                scheduled = True

            if scheduled:
                continue

            # Phase 3: LAST RESORT -- no spot VM can take this task
            # within Dspot. Fall back to on-demand, judged against the
            # real deadline D rather than Dspot (an on-demand VM is not
            # exposed to hibernation, so it needs no migration reserve),
            # drawing a fresh VM from the elastic M^o pool if none of the
            # running ones fit. This mirrors HADS's own Phase (c).
            #
            # This phase did not exist. The loop simply fell through, and
            # a task that fit nowhere on spot was left OUT OF THE
            # ALLOCATION ENTIRELY -- never assigned, never started, never
            # run, with assigned_vm/start_time/finish_time all None. And
            # because Metrics guards every aggregate on `task.finish_time`,
            # such a task contributed no cost, no makespan and no deadline
            # miss: it vanished from the results instead of appearing as a
            # failure.
            #
            # It bites hardest when Dspot is tight. At n=50 the shared
            # pool gives D=312.5s, so Dspot = 312.5 - 192.5 = 120s, and a
            # 286s task needs 143s on a speed-2 VM -- placeable nowhere on
            # spot once the speed-4 VMs fill. Measured across 4 seeds:
            # HADS lost 0 tasks, BurstHADS lost 24, and the whole sweep
            # reported BurstHADS at 92% completion with its cost and
            # makespan computed over the surviving 92% only.
            for vm in sorted(self.ondemand_vms, key=lambda v: v.cost_rate):
                if not self._launches.can_launch(vm):
                    continue
                if self._check_schedule(task, vm, vm_tasks, vm_memory,
                                        self.D):
                    self._launches.commit(vm)
                    allocation[task.task_id] = vm.id
                    vm_tasks.setdefault(vm.id, []).append(task)
                    vm_memory[vm.id] = (vm_memory.get(vm.id, 0)
                                        + task.memory_req)
                    if vm.id not in selected_vm_ids:
                        selected_vms.append(vm)
                        selected_vm_ids.add(vm.id)
                    scheduled = True
                    break
            if scheduled:
                continue

            # A new VM of the cheapest on-demand type, within its instance
            # limit, that can take the task before D.
            in_limit = [t for t in self._od_catalogue
                        if self._launches.can_launch_type("ondemand", t["vm_type"])]
            if not in_limit:
                raise NoFeasibleSchedule(
                    f"BurstHADS: no placement for task {task.task_id} within "
                    f"D={self.D:.1f}s and the instance limits.")
            tpl = next((t for t in in_limit
                        if self._check_schedule(task, make_vm(t, -1), vm_tasks,
                                                vm_memory, self.D)), None)
            if tpl is not None:
                new_vm = self._launch_new_ondemand_vm(0.0, tpl)
                allocation[task.task_id] = new_vm.id
                vm_tasks.setdefault(new_vm.id, []).append(task)
                vm_memory[new_vm.id] = (vm_memory.get(new_vm.id, 0)
                                        + task.memory_req)
                selected_vms.append(new_vm)
                selected_vm_ids.add(new_vm.id)
                continue

            # Not even a brand-new, empty on-demand VM can run this task
            # before D. Fail loudly rather than dropping it silently --
            # HADS raises here too.
            raise RuntimeError(
                f"BurstHADS: no feasible placement for task "
                f"{task.task_id} before deadline D={self.D:.1f}s "
                f"(Dspot={self.Dspot:.1f}s)."
            )

        return SchedulingSolution(allocation, selected_vms)

    def _check_schedule(self, task, vm, vm_tasks, vm_memory, dspot):
        """
        Feasibility check for assigning task to vm.
        Enforces:
          - Dspot (makespan constraint) -- via multi-core list
            scheduling of the tentative task set, not a flat sum.
          - VM memory capacity (paper Constraint 3)
        """
        current_mem = vm_memory.get(vm.id, 0)
        if current_mem + task.memory_req > vm.memory_mb:
            return False

        tasks_if_added = vm_tasks.get(vm.id, []) + [task]
        return self._vm_makespan_static(tasks_if_added, vm) <= dspot

    def _check_memory_only(self, task, vm, vm_memory):
        """Constraint 3 alone -- used inside local search, where
        Dspot feasibility is left to fitness() rather than a hard
        per-swap gate (see _local_search)."""
        current_mem = vm_memory.get(vm.id, 0)
        return current_mem + task.memory_req <= vm.memory_mb

    # ------------------------------------------------------------------
    # ALGORITHM 3 — LOCAL SEARCH
    # ------------------------------------------------------------------

    def _local_search(self, solution, max_attempt, swap_rate, dspot):
        """
        Paper Algorithm 3: pick ONE destination VM for this whole
        call and try swap_rate of the tasks onto it, max_attempt
        times, keeping whichever attempt scored best. The destination
        used to be re-rolled every single attempt, which meant every
        attempt was testing a completely different random VM --
        "local" search in name only. Also: the paper's own pseudocode
        only re-checks Constraint 3 (memory) before accepting a swap,
        not Dspot -- a swap that blows the makespan is instead
        punished by fitness() when the candidate is scored below,
        which is what Eq 9 is for.
        """
        best   = solution.clone()
        n_swap = max(1, int(swap_rate * len(self.all_tasks)))
        vm_map   = {vm.id: vm for vm in self.all_vms}
        task_map = {t.task_id: t for t in self.all_tasks}

        swap_candidates = (
            best.selected_vms +
            [v for v in self.spot_vms if v not in best.selected_vms]
        )
        if not swap_candidates:
            return best
        dest_vm = random.choice(swap_candidates)

        for _ in range(max_attempt):
            candidate = best.clone()

            # Bucket view of this candidate's assignment.
            vm_tasks = {}
            for tid, vid in candidate.allocation.items():
                task = task_map.get(tid)
                if task is not None:
                    vm_tasks.setdefault(vid, []).append(task)
            vm_memory = self._compute_vm_memory(candidate)

            tasks_to_swap = random.sample(
                self.all_tasks,
                min(n_swap, len(self.all_tasks))
            )

            for task in tasks_to_swap:
                old_vm_id = candidate.allocation.get(task.task_id)
                old_vm    = vm_map.get(old_vm_id)

                if old_vm and task in vm_tasks.get(old_vm_id, []):
                    vm_tasks[old_vm_id].remove(task)
                    vm_memory[old_vm_id] = max(
                        0, vm_memory.get(old_vm_id, 0)
                        - task.memory_req)

                if self._check_memory_only(task, dest_vm, vm_memory):
                    candidate.allocation[task.task_id] = dest_vm.id
                    vm_tasks.setdefault(dest_vm.id, []).append(task)
                    vm_memory[dest_vm.id] = (vm_memory.get(dest_vm.id, 0)
                                             + task.memory_req)
                else:
                    # Revert -- Constraint 3 is a hard constraint the
                    # paper's Algorithm 3 pseudocode doesn't restate
                    # here but that still must hold everywhere.
                    if old_vm:
                        candidate.allocation[task.task_id] = old_vm_id
                        vm_tasks.setdefault(old_vm_id, []).append(task)
                        vm_memory[old_vm_id] = (vm_memory.get(old_vm_id, 0)
                                                + task.memory_req)

            if dest_vm not in candidate.selected_vms:
                candidate.selected_vms.append(dest_vm)

            if (self._fitness(candidate, dspot) <
                    self._fitness(best, dspot)):
                best = candidate

        return best

    # ------------------------------------------------------------------
    # ALGORITHM 1 — ILS
    # ------------------------------------------------------------------

    def _iterated_local_search(self, initial,
                                max_iteration=200,
                                max_attempt=50,
                                swap_rate=0.10,
                                max_failed=20,
                                relaxed_rate=0.25):
        # On-demand VMs the search can use: those of the initial solution
        # (Phase 3). Local search only ever moves tasks among selected VMs
        # and unused spot VMs, so this set is fixed for the whole search
        # and _fitness's normaliser is the same for every candidate.
        self._eq9_ondemand = [v for v in initial.selected_vms
                              if v.market == VM.ONDEMAND]
        current  = self._local_search(initial, max_attempt,
                                      swap_rate, self.Dspot)
        best     = current.clone()

        used_ids    = {vm.id for vm in best.selected_vms}
        unused_spot = [v for v in self.spot_vms
                       if v.id not in used_ids]

        relaxed_dspot = self.Dspot
        it_best       = 0
        it_last_relax = 0

        for it in range(max_iteration):
            if unused_spot:
                new_vm = random.choice(unused_spot)
                current.selected_vms.append(new_vm)
                unused_spot = [v for v in unused_spot
                               if v.id != new_vm.id]

            # Algorithm 1, lines 11-13:
            #   if (it - it_best) > max_failed then
            #       RDspot <- RDspot + (relaxed_rate * RDspot)
            #
            # The paper applies this ONCE PER max_failed-length stall
            # window. Written as a bare per-iteration test it instead
            # fires on EVERY iteration for as long as the search is
            # stalled, so a 160-iteration stall compounds 1.25 a hundred
            # and sixty times. Measured on n=100 before this fix: Dspot
            # went from 1683.6 to 3.45e18, a growth factor of 2.05e15.
            #
            # That is not a relaxation, it is the removal of the
            # constraint -- _fitness's infeasibility gate
            # ("if makespan > dspot: return 1.0") can never fire again,
            # so the ILS spends most of its budget optimising with the
            # deadline switched off. And Dspot is not an arbitrary
            # bound: the paper defines it as "the worst-case estimated
            # makespan, which guarantees that there will always have
            # enough spare time to migrate tasks of any hibernated spot
            # VM to other VMs and to execute them before the deadline
            # D." Abolishing it means BurstHADS packs with NO migration
            # reserve, which is precisely the slack its hibernation
            # handling depends on -- and it is why BurstHADS was losing
            # to HADS (whose single-pass greedy enforces Dspot strictly)
            # in exactly the hibernation scenarios it should win.
            #
            # Two corrections: relax at most once per stall window, and
            # never relax past D itself. A candidate whose makespan
            # exceeds the real deadline misses regardless, so treating
            # RDspot > D as "feasible" cannot buy anything real.
            if (it - it_best) > max_failed and (it - it_last_relax) > max_failed:
                relaxed_dspot = min(
                    relaxed_dspot + (relaxed_rate * relaxed_dspot),
                    self.D,
                )
                it_last_relax = it

            candidate = self._local_search(current, max_attempt,
                                           swap_rate, relaxed_dspot)

            if (self._fitness(candidate, relaxed_dspot) <
                    self._fitness(best, relaxed_dspot)):
                best    = candidate.clone()
                it_best = it

            current = candidate

        return best

    # ------------------------------------------------------------------
    # BURSTABLE VM ALLOCATION (Algorithm 1 Part 2)
    # ------------------------------------------------------------------

    def _allocate_burstable_vms(self, solution):
        """
        Algorithm 1, Part 2: after the ILS produces a spot-only
        solution, launch n = round(burst_rate * |selected_vms|)
        burstable VMs from the elastic M^b pool and use them
        PROACTIVELY, at scheduling time -- not just reactively during
        hibernation rescue. Every task moved here runs in BASELINE
        mode (Section 3.2: proactive burst allocation earns credits,
        it doesn't spend them -- that's reserved for reactive
        hibernation rescues, Algorithm 4).

        Priority:
          1. Tasks currently projected (via list-scheduling the ILS's
             own solution) to finish AFTER Dspot -- these are exactly
             the tasks the proactive step exists to save, one per
             burstable VM (Section 3.2: a burstable VM only ever
             holds one task at a time).
          2. Any leftover burstable VMs get the single
             globally-latest-finishing remaining task, also in
             baseline mode, as a small proactive load-balancing bonus.

        This previously did nothing at all (`return solution`
        unchanged) -- burstable VMs only ever got used reactively, on
        hibernation, never proactively the way Algorithm 1 describes.
        """
        # Algorithm 1, line 23:  n <- ceil(burst_rate * |S_best.selected_vms|)
        # This used round(), which returns ZERO burstable VMs whenever the
        # ILS selects one or two spot VMs (round(0.2*2) = round(0.4) = 0) --
        # silently switching off the entire mechanism that distinguishes
        # Burst-HADS from HADS. The paper's ceiling guarantees at least one
        # burstable VM whenever any VM is selected.
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
            burst_vm  = remaining_burst[0]
            old_vm_id = solution.allocation.get(task.task_id)
            old_vm    = vm_map.get(old_vm_id)
            if old_vm is None or not burst_vm.can_fit_task(task):
                continue
            # Only move the task if baseline execution is actually an
            # IMPROVEMENT on where it already is.
            #
            # This step exists to rescue tasks projected to overrun Dspot,
            # and the gain is real when the task is queued behind others:
            # alone on a dedicated burstable VM it can finish sooner even
            # at baseline speed. But the move was previously gated on
            # can_fit_task() alone -- a MEMORY check -- so a task was
            # relocated whether or not it helped. Baseline mode runs at
            # baseline_fraction of the VM's speed (0.20 * 2 = 0.4 here),
            # so a task moved when it did not need to be takes 5x longer
            # and becomes the makespan. Measured at n=100 before this
            # guard: a 348 s task landed on a t3.large at effective speed
            # 0.4, ran for 957 s alone, set the whole makespan and missed
            # a 625 s deadline that every other task met.
            if self._baseline_finish(task, burst_vm) >= ft:
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
                # Same improvement test as the violator loop above -- this
                # opportunistic pass must not make a task worse either.
                if self._baseline_finish(task, burst_vm) >= ft:
                    continue
                task.baseline_mode = True
                solution.allocation[task.task_id] = burst_vm.id
                if burst_vm not in solution.selected_vms:
                    solution.selected_vms.append(burst_vm)
                remaining_burst.pop(0)

        return solution

    def _baseline_finish(self, task, burst_vm):
        """
        Projected finish time for `task` running ALONE on `burst_vm` in
        baseline mode -- the mode Algorithm 1's proactive allocation uses,
        which by design runs at only baseline_fraction of the VM's speed
        so that CPU credits accrue rather than drain.
        """
        sp = burst_vm.effective_speed(burst_mode=False)
        if sp <= 0:
            return float('inf')
        return (task.exec_time / sp) * (1.0 + task.checkpoint_overhead)

    def _launch_burstable_vms(self, n):
        """
        Pull n VMs out of M^b -- same type/speed/price as whatever
        burstable VM(s) are already in the pool. Mirrors
        _launch_new_ondemand_vm's M^o handling. Each is billed from this
        launch (LaunchCounter.commit), used or not, and -- being exempt from
        idle termination -- until the end of the run: TCC23's burstables are
        a sunk cost, which is what makes a rescue onto one free at the margin.
        """
        if not self._burst_catalogue:
            return []
        tpl = self._burst_catalogue[0]

        launched = []
        for _ in range(n):
            if not self._launches.can_launch_type("ondemand", tpl["vm_type"]):
                break                   # IPDPS: "Not fullfill N_burst"
            new_vm = make_vm(tpl, self._next_new_vm_id)
            self._next_new_vm_id += 1
            new_vm.state = VM.IDLE

            self.burstable_vms.append(new_vm)
            if new_vm not in self.all_vms:
                self.all_vms.append(new_vm)
            if new_vm not in self.vms:
                self.vms.append(new_vm)
            self._launches.commit(new_vm)
            launched.append(new_vm)
        return launched

    # ------------------------------------------------------------------
    # FITNESS FUNCTION  (Equation 9)
    # ------------------------------------------------------------------

    def _fitness(self, solution, dspot):
        """
        Equation 9, verbatim from the paper text (not the GitHub
        reference code, which diverges here -- see below):

            fitness(S, Dspot) = 1,                     if violates Dspot
                              = a*cost + (1-a)*mkp,     otherwise

        This was briefly changed to `float('inf')` on the theory that
        the real IPDPS.py source (which sets
        `makespan = float("inf")` on a Dspot violation) was the
        more authoritative reference. Rereading the paper's own
        Section 3.2 text corrects that: Eq 9 states the penalty is
        exactly 1, not infinity, and this is not an arbitrary weaker
        choice on the authors' part -- it's sound BECAUSE of how the
        paper defines normalization one paragraph earlier: cost is
        divided by (the most expensive spot VM's cost over Dspot
        periods, times the max number of deployable VMs) and makespan
        by Dspot itself, so both terms lie in [0,1] for any FEASIBLE
        solution by construction. A flat 1.0 is therefore already an
        upper bound on every feasible solution's fitness (equality
        only in the pathological worst case), which is exactly what a
        tie-breaking infeasibility sentinel needs to be -- no need for
        an unbounded value, and using one contradicts the equation
        this method is supposed to implement. Reverted to 1.0.

        The GitHub repo's IPDPS.py -- which, per its own
        `burstable_factor` config and burst-allocation logic, looks to
        be the real Burst-HADS implementation -- uses `inf` here
        instead. That's a genuine, confirmed paper-vs-code
        discrepancy in the reference implementation itself, not a
        transcription error on either side; it's called out here
        rather than silently resolved because whoever reads this
        later should know the two sources disagree and that this
        method deliberately follows the paper, since the paper is
        what's actually being cited and reproduced.
        """
        makespan, cost = self._evaluate(solution)

        # Eq 1 normalization (paper prose, one paragraph before Eq 9):
        # cost divided by the most expensive VM's cost over Dspot periods
        # times the max number of deployable VMs; makespan divided by
        # Dspot.
        #
        # WHY THE BOUND FAILED. The flat infeasibility score is sound only
        # while every feasible score is <= 1, i.e. while normalised cost
        # is <= 1. The normaliser used to cover spot VMs alone, on the
        # premise that nothing else is in the search space -- but
        # _initial_solution's Phase 3 places tasks on on-demand VMs, their
        # cost enters _evaluate, and feasible scores can then exceed 1.0,
        # at which point the ILS prefers an infeasible candidate (one whose
        # makespan exceeds even D) and nothing downstream re-checks it.
        #
        # The normaliser therefore covers every VM the search can place a
        # task on: the spot pool plus the on-demand VMs of the initial
        # solution (the ILS never adds on-demand VMs), at the dearest rate
        # among them. That restores the bound the paper's 1.0 relies on.
        pool = list(self.spot_vms) + list(getattr(self, "_eq9_ondemand", []))
        if pool:
            max_cost = (max(v.cost_rate for v in pool) * dspot * len(pool))
        else:
            max_cost = 0

        if makespan > dspot:
            return 1.0

        norm_cost     = cost / max_cost    if max_cost > 0 else 0
        norm_makespan = makespan / dspot   if dspot    > 0 else 0
        return (self.alpha * norm_cost
                + (1 - self.alpha) * norm_makespan)

    def _evaluate(self, solution):
        vm_load  = self._compute_vm_load(solution)
        makespan = max(vm_load.values()) if vm_load else 0
        vm_map   = {vm.id: vm for vm in self.all_vms}
        # Cost proxy at scheduling time: each VM is billed for its
        # own makespan (the actual deployed-duration billing model
        # lives in metrics.py; this is only the ILS's internal
        # estimate used to rank candidate solutions before anything
        # actually runs).
        cost     = sum(load * vm_map[vid].cost_rate
                       for vid, load in vm_load.items()
                       if vid in vm_map)
        return makespan, cost

    def _compute_vm_load(self, solution):
        """
        {vm_id: this VM's own makespan} under the given allocation,
        via list-scheduling across the VM's vcpu_count cores -- not a
        flat sum of task times, which would still treat a 4-vCPU VM
        as if it could only run one task at a time.
        """
        vm_map  = {vm.id: vm for vm in self.all_vms}
        buckets = {}
        for task in self.all_tasks:
            vm_id = solution.allocation.get(task.task_id)
            if vm_id is None:
                continue
            buckets.setdefault(vm_id, []).append(task)

        vm_load = {}
        # List-schedule each VM's tasks in EXECUTION order: memory
        # descending, the order _apply_solution queues them and
        # start_next_if_free starts them (and the order _initial_solution
        # already plans in). Bucketing by iterating all_tasks lists them
        # in task-id order, and list scheduling across vcpu_count cores is
        # order-dependent, so without this sort the ILS scored -- and the
        # proactive burstable step chose violators from -- a schedule
        # other than the one that runs.
        for vm_id, tasks in buckets.items():
            vm = vm_map.get(vm_id)
            if vm is None:
                continue
            tasks.sort(key=lambda t: t.memory_req, reverse=True)
            vm_load[vm_id] = self._vm_makespan_static(tasks, vm)
        return vm_load

    def _compute_vm_memory(self, solution):
        """Returns {vm_id: total memory MB assigned}."""
        vm_memory = {}
        for task in self.all_tasks:
            vm_id = solution.allocation.get(task.task_id)
            if vm_id is None:
                continue
            vm_memory[vm_id] = (vm_memory.get(vm_id, 0)
                                + task.memory_req)
        return vm_memory

    # ------------------------------------------------------------------
    # APPLY SOLUTION TO VM QUEUES
    # ------------------------------------------------------------------

    def _apply_solution(self, solution):
        """
        Translate allocation map to VM queues.
        Sort tasks within each VM by memory descending (paper Algorithm 2).
        Reserve memory on each VM.
        """
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
            # Sort by memory descending (paper Algorithm 2)
            tasks.sort(key=lambda t: t.memory_req, reverse=True)
            vm.tasks = tasks
            self._launches.commit(vm)
            for task in tasks:
                task.assigned_vm = vm
                vm.reserve_memory(task)

    # ------------------------------------------------------------------
    # TERMINATED VM REMOVAL
    # ------------------------------------------------------------------

    def _remove_terminated_vm(self, vm):
        """Remove a terminated VM from active pools."""
        for pool in [self.spot_vms, self.burstable_vms, self.ondemand_vms]:
            if vm in pool:
                pool.remove(vm)

    # ------------------------------------------------------------------
    # DYNAMIC SCHEDULER -- select_vm (Algorithm 4)
    # ------------------------------------------------------------------
    #
    # Faithful implementation of the paper's Burst Migration Procedure
    # (Section 3.4, Algorithm 4). No reordering, no shortcuts:
    #
    #   Attempt 1 (lines 3-13):  migrate to an IDLE burstable VM with
    #       enough accrued CPU credits, executed in burst mode. A
    #       burstable VM is only ever a candidate while idle, so it
    #       can never receive more than one migrated task at a time
    #       (Section 3.2: "a single task per burstable instance at a
    #       time... induces CPU credits accumulation").
    #   Attempt 2 (lines 14-28): migrate to an already-active
    #       NON-burstable VM (idle or busy, spot or on-demand). K is
    #       built by sort_by_market(IR union BR), which "prioritizes
    #       idle spot VMs" and puts spot ahead of on-demand.
    #   Attempt 3 (lines 29-40): last resort -- launch/assign a NEW
    #       non-burstable on-demand VM, gated on the same deadline
    #       test as the paper (start_ij + e_ij + omega < D).
    #
    # check_migration(t_i, vm_j, D) is implemented as _check_migration:
    # memory feasibility + finish-time-before-deadline feasibility
    # (via the VM's own multi-core list-scheduling estimate, so a
    # migration target's real queueing behavior is accounted for
    # correctly regardless of vcpu_count), plus the CPU-credit test
    # when the candidate is burstable, plus (Section 3.4) a spot-VM
    # spare-time margin -- see below.
    # ------------------------------------------------------------------

    def _check_migration(self, task, vm, current_time, deadline,
                          burst_mode=False):
        """
        check_migration(t_i, vm_j, D) -- Algorithm 4.

        Section 3.4 (paper text, not just the pseudocode): "if vmj is
        a spot VM, the function check_migration should also verify if
        there will be enough spare time in vmj between the end of the
        execution of vmj tasks (including task ti) and the deadline
        D... The spare time has to be greater than the execution time
        of the longest task scheduled to vmj, ensuring... if a
        hibernation occurs, there will be enough time to migrate and
        execute all affected tasks before the deadline D." This was
        previously missing entirely -- every migration target used
        the same flat deadline test regardless of market, so a spot
        VM that looked deadline-safe right now could still be picked
        even though it would leave no slack to recover from its OWN
        possible future hibernation. Only applies to spot targets: a
        busy/idle on-demand VM was never exposed to hibernation risk
        in the first place, and a burstable target already went
        through the separate CPU-credit gate above.
        """
        if not vm.can_fit_task(task):
            return False

        speed  = (vm.effective_speed(burst_mode=burst_mode)
                 if vm.is_burstable else vm.speed)
        finish = vm.estimate_finish_time(task, current_time, task_speed=speed)
        if finish > deadline:
            return False

        if vm.is_burstable and burst_mode:
            # Baseline mode never needs credits -- that is what makes
            # it "baseline". Only an actual burst request has to pass
            # the credit-sufficiency test.
            required = vm.credits_required(task.remaining_time / speed)
            if not vm.can_burst(required):
                return False

        if vm.is_spot:
            # "the longest task scheduled to vmj [including ti]" --
            # every task already queued/running there, plus the
            # candidate itself, each measured by its own execution
            # time on vmj (same convention Dspot itself uses: full
            # exec_time, not remaining_time, since this is a
            # worst-case safety margin against a FUTURE hibernation,
            # not a statement about this task's current progress).
            candidate_tasks = list(vm.tasks) + [task]
            longest = max(t.exec_time / vm.speed for t in candidate_tasks)
            spare   = deadline - finish
            if spare <= longest:
                return False

        return True

    def select_vm(self, task, job, current_time):
        """Algorithm 4 entry point: Attempts 1-2, then Attempt 3."""
        vm = self._attempt_paper_migration(task, current_time)
        if vm is not None:
            return vm
        return self._attempt_ondemand_fallback(task, current_time)

    def _attempt_paper_migration(self, task, current_time):
        """Algorithm 4, Attempts 1 and 2 (everything short of on-demand)."""
        deadline = self.D

        # Attempts 1-2 take only VMs this run has launched. Algorithm 4's
        # inputs are "the sets of idle, busy, and non-launched regular
        # on-demand VMs (IR, BR and Mo)": IR and BR are running VMs, and
        # non-launched capacity is Attempt 3's on-demand pool alone. Pool VMs
        # no one launched used to qualify (DEVIATIONS U6).
        # Attempt 1 -- idle burstable VM with enough credits
        idle_burstable = [
            v for v in self.burstable_vms
            if v.state not in (VM.HIBERNATED, VM.TERMINATED) and not v.tasks
            and self._launches.is_launched(v)
        ]
        for vm in sorted(idle_burstable, key=lambda v: v.cost_rate):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time,
                                              deadline, burst_mode=True)):
                self._launches.commit(vm)
                return vm

        # Attempt 2 -- active non-burstable VM.
        # K = sort_by_market(IR union BR): spot before on-demand, idle
        # before busy within each market ("prioritizes idle spot VMs").
        def _k_sort_key(v):
            market_rank = 0 if v.is_spot else 1
            busy_rank   = 1 if v.tasks else 0
            return (market_rank, busy_rank, v.cost_rate)

        active_nonburstable = [
            v for v in (self.spot_vms + self.ondemand_vms)
            if v.state not in (VM.HIBERNATED, VM.TERMINATED)
            and self._launches.is_launched(v)
        ]
        for vm in sorted(active_nonburstable, key=_k_sort_key):
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm

        return None

    def _attempt_ondemand_fallback(self, task, current_time):
        """
        Algorithm 4, Attempt 3 -- last resort on-demand VM.

        The paper's own inputs to this algorithm are "the sets of
        idle, busy, and NON-LAUNCHED regular on-demand VMs (IR, BR
        and M^o, respectively)" -- M^o is a pool you draw fresh VMs
        from, not one fixed machine. So: try every on-demand VM
        already running first (cheapest/most-loaded-appropriately
        first); only if none of them can make the deadline do we pull
        a new one out of M^o. That pool is not capped, matching a
        real cloud where you can always buy one more on-demand
        instance -- the paper never says otherwise, and capping it at
        one would make this a different, weaker scheduler than the
        one being evaluated.
        """
        deadline = self.D
        candidates = sorted(
            [v for v in self.ondemand_vms
             if v.state not in (VM.HIBERNATED, VM.TERMINATED)],
            key=lambda v: v.cost_rate
        )
        for vm in candidates:
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm

        in_limit = [t for t in self._od_catalogue
                    if self._launches.can_launch_type("ondemand", t["vm_type"])]
        if not in_limit:
            return self._capped_fallback(task, current_time)

        # Draw a fresh VM from M^o: "sort by price(Mo); for each vmj in Mo:
        # if start + eij + omega < D: start vm". STARTUP_LATENCY stands in
        # for omega (time to deploy a new VM). Types walked cheapest first,
        # each within its instance limit.
        for tpl in in_limit:
            probe = make_vm(tpl, -1)
            # Fix 20 (U10): execution charges (1 + overhead) on every task.
            finish = (current_time + STARTUP_LATENCY
                      + task.remaining_time / probe.speed
                      * (1.0 + task.checkpoint_overhead))
            if probe.can_fit_task(task) and finish <= deadline:
                return self._launch_new_ondemand_vm(current_time, tpl)
        new_vm = self._launch_new_ondemand_vm(current_time, in_limit[0])

        # Even a brand-new on-demand VM can't make the deadline -- the
        # task is already unsavable. Not part of Algorithm 4: rather
        # than orphaning it, still run it there (late) so it shows up
        # as a deadline miss instead of vanishing from the simulation.
        return new_vm

    def _launch_new_ondemand_vm(self, current_time, tpl=None):
        """
        Pull one VM out of M^o -- same type/speed/price/vcpu_count as
        whatever on-demand VM(s) are already in the pool. Billed from this
        launch (LaunchCounter.commit).
        """
        # `tpl`: an entry of self._od_catalogue; default the cheapest type.
        new_vm = make_vm(tpl or self._od_catalogue[0], self._next_new_vm_id)
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
        """Used by work stealing policy."""
        return deadline - vm.estimate_finish_time(task, current_time)
