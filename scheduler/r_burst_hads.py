"""
R-BurstHADS: Reinforced Burst Hibernation-Aware Dynamic Scheduler

FORMAL CONTRIBUTION:
====================
BurstHADS (scheduler/burst_hads.py) is a faithful, unmodified
implementation of Algorithm 4 from the paper: on hibernation it tries
an idle burstable VM first, then any active non-burstable VM, then a
last-resort on-demand VM. A burstable VM can only ever hold one
migrated task at a time (Section 3.2), so once the pool is fully
saturated (all spot VMs hibernated simultaneously) and that single
burstable VM is occupied, every further rescued task piles onto the
SAME single on-demand VM (subject to its own vcpu_count concurrency),
a bottleneck the paper's static pool has no other way to relieve.

R-BurstHADS introduces DEADLINE-AWARE PREEMPTIVE PROVISIONING on top
of the unmodified Algorithm 4 procedure, to relieve exactly that
bottleneck:

THEOREM 1 — Preemptive Provisioning Decision:
  Provision preemptively for VM v if:
    P(v hibernates) * C_reactive > C_proactive

  P(v hibernates) = 1 - exp(-lambda_v * e_avg / s_v)
  C_reactive  = n_v * e_avg * (r_od/theta_od - r_s/theta_s)
  C_proactive = T_startup * r_s + epsilon,   epsilon = 0

  lambda_v is v's DECLARED per-type rate (main.py), s_v its per-core
  speed, theta = speed * vcpu_count. The exposure horizon is one average
  task on v. This docstring used to state it as the deadline D, which the
  code never computed; _preemptive_provision explains why the one-task
  horizon is kept and what results are sensitive to it.

THEOREM 2 — Adaptive VM Count:
  At hibernation time t with n_rescued tasks:
    n_VMs = ceil(n_rescued / TASKS_PER_VM_CAP)

  TASKS_PER_VM_CAP bounds makespan:
    makespan <= t_hib + TASKS_PER_VM_CAP * avg_exec / speed

  Without this: O(n) makespan (all tasks queue sequentially on 1 VM)
  With this:    O(1) makespan relative to TASKS_PER_VM_CAP

VM TYPE SELECTION (tier 3, _provision_one_more):
  Spot VM if slack > STARTUP_LATENCY * SLACK_MULTIPLIER, it finishes by D
  with the Section 3.4 spare-time margin, and its type is within its
  launch limit; otherwise a burstable if it finishes by D. Both boot for
  STARTUP_LATENCY (fix 21). This docstring used to say a burstable is
  chosen when the deadline is too tight for spot startup; measured, that
  never selected one, before fix 21 or after: the spot launch limit chose
  1,401 of the 1,453 burstables and the spare-time rule 52
  (experiments/diag_launch21_f21.txt, 7,200 runs).

R-BurstHADS never overrides the paper's own migration attempts -- it
calls BurstHADS's _attempt_paper_migration / _attempt_ondemand_fallback
directly (see select_vm below) and only wraps its own provisioning
tiers around them, so any future fix to the baseline's Algorithm 4
fidelity is inherited automatically. (Previously select_vm
re-implemented tiers 2-4 inline instead of actually delegating to
_attempt_paper_migration as this docstring always claimed -- that
inline copy used raw sum(remaining_time / vm.speed) queue-time math,
which assumed every VM was a single sequential worker regardless of
vcpu_count, and skipped _check_migration's shared feasibility/credit
logic entirely. It now genuinely delegates, so it inherits the
baseline's multi-core-aware feasibility test for free.)
"""

import math
from scheduler.burst_hads import BurstHADS
from models.vm import VM
from simulation.provisioning_event import ProvisioningEvent, STARTUP_LATENCY

# ── CONSTANTS ─────────────────────────────────────────────────────────────────

PREEMPTIVE_RISK_THRESHOLD = 0.05   # provision if P(hibernation) > 5%

# INSTANCE PARITY (2026-08-27): these are now only a LAST-RESORT
# fallback for a pool that contains no spot VM at all. R-BurstHADS
# resolves the instance type it provisions from its own pool at
# construction time (_resolve_spot_template), so it can never obtain a
# type the baselines' planners could not also have selected. Previously
# these constants were used unconditionally, and c5.xlarge was absent
# from the shared pool -- giving R-BurstHADS exclusive access to the
# most cost-efficient instance in the study (261 units/$ vs c5.large
# spot's 131) and inflating its measured advantage accordingly.
SPOT_TYPE     = "c5.xlarge"
SPOT_SPEED    = 2.0
SPOT_RATE     = 0.0612 / 3600
SPOT_MEM_GB   = 8.0
SPOT_HIB_RATE = 0.04 / 3600
SPOT_VCPU     = 4

BURST_TYPE          = "t3.large"
BURST_SPEED         = 1.7
BURST_RATE          = 0.0832 / 3600
BURST_MEM_GB        = 8.0
BURST_CREDITS_INIT  = 144.0
BURST_BASELINE_FRAC = 0.20
BURST_VCPU          = 2   # forced to 1 internally by VM (burstable rule)

SLACK_MULTIPLIER  = 2.0   # spot viable if slack > 2 * STARTUP_LATENCY
MAX_VMS_PER_EVENT = 10    # safety cap on VMs per saturation event

# Theorem 2 (ORIGINAL form): max tasks per provisioned VM.
# RETIRED as the provisioning trigger on 2026-08-27 -- fleet size is now
# derived from the deadline in RBurstHADS._vms_needed_for_deadline().
# Kept so the module docstring's original Theorem 2 statement stays
# readable and any external reference still resolves. Nothing reads it.
#   old rule: makespan <= t_hib + cap * avg_exec/speed
#   cap=8: 8 * 57s = 456s queue per VM at speed=4
TASKS_PER_VM_CAP = 8


class RBurstHADS(BurstHADS):
    """
    Dynamic BurstHADS with deadline-aware adaptive VM provisioning.

    Adds two behaviors to BurstHADS:
    1. After ILS: pre-provisions replacement spot VMs for high-risk VMs
       (Theorem 1 cost-benefit decision)
    2. After hibernation: provisions enough VMs to bound makespan
       (Theorem 2 TASKS_PER_VM_CAP limit)
    """

    def __init__(self, vms, all_tasks, jobs,
                 deadline=None, alpha=0.5, burst_rate=0.2):
        super().__init__(vms, all_tasks, jobs,
                         deadline=deadline,
                         alpha=alpha,
                         burst_rate=burst_rate)

        self._next_vm_id               = 100
        self.provisioned_vms           = []
        self._pending_provision_events = []
        self._last_saturation_response_time = -1.0
        # Track total rescue load across all hibernation events
        self._total_rescued = 0
        # Flag: True after we've responded to the current saturation event
        # Reset to False when a new hibernation occurs
        self._saturation_handled = False
        self._n_hibernated_vms = 0  # count of hibernated spot VMs seen

        # Instance parity: snapshot the provisioning template from the
        # ORIGINAL pool, before any provisioning appends to self.spot_vms.
        self._spot_tpl = self._resolve_spot_template()

    def _resolve_spot_template(self):
        """
        Pick the instance type this scheduler will provision, FROM ITS OWN
        POOL, rather than from a hardcoded private type.

        Policy: the best EXPECTED SURVIVING throughput per dollar,

            (speed * vcpu_count / cost_rate) * exp(-lambda_v * D)

        that is, raw capacity per dollar discounted by the probability
        the machine is still there at the deadline. The survival term is
        the complement of the same 1 - exp(-lambda_v * D) Theorem 1
        already uses for its provisioning decision, so the selector and
        the provisioning trigger now reason about risk through one
        formula rather than two.

        Why the discount is not optional. The criterion was previously
        raw throughput-per-dollar with no risk term at all, and it picked
        the safe instance only because this catalogue's cheapest-per-unit
        type also happened to carry a low lambda. That is the catalogue
        being kind, not the rule being right: reprice m5.xlarge slightly
        and the same line of code would begin buying replacement capacity
        167x more likely to be hibernated than what it replaced, silently
        defeating the premise of the extension.

        Correcting the per-core speeds (see main.PER_CORE_SPEED) then
        turned that from advisable into mandatory. With instance size no
        longer counted twice, c5.large and c5.xlarge score an identical
        130.7 units per dollar-hour -- exactly as they should, since on
        AWS a c5.xlarge is two c5.larges at twice the price. Something
        has to separate them, and expected survival is the principled
        something.

        Still drawn from the same catalogue every scheduler's planner
        sees, so the reactive-provisioning contribution is measured on
        equal hardware terms rather than on exclusive access to a better
        instance. Falls back to the module SPOT_* constants only if the
        pool contains no spot VM at all.
        """
        cands = [v for v in self.spot_vms if v.cost_rate > 0]
        if not cands:
            return dict(vm_type=SPOT_TYPE, speed=SPOT_SPEED,
                        cost_rate=SPOT_RATE, mem_gb=SPOT_MEM_GB,
                        hib_rate=SPOT_HIB_RATE, vcpu=SPOT_VCPU)

        horizon = getattr(self, "D", None) or 0.0

        def survival(v):
            return math.exp(-v.hibernation_rate * horizon)

        # Survival is a FILTER, not a weight. Measured 2026-09-13, a
        # weighted score was actively harmful: it separated c5.large from
        # c5.xlarge by 126.9 to 125.6, a 1% margin arising entirely from
        # a lambda differential this study invented for illustration, and
        # on that basis picked the smaller machine. An A/B on three cells
        # (experiments/template_ab.py) showed c5.xlarge strictly better
        # on BOTH axes every time -- by 2.4% to 36.3% on makespan and 5.0%
        # to 25.3% on cost. The weighting was optimising a 1% fiction and
        # paying up to 36% for it.
        #
        # Mechanism, and it is the interaction with the fairness fix:
        # _check_migration enforces the Section 3.4 spot spare-time rule
        # on provisioned VMs now, and a 4-vCPU machine clears a rescued
        # batch in half the wall-clock of two 2-vCPU machines, so it
        # leaves more spare and passes the test far more often. The
        # smaller machine fails it and the work falls through to the
        # on-demand tier, which is both slower to reach and the most
        # expensive thing on the price list.
        #
        # So: exclude anything unlikely to survive the deadline at all --
        # which is the risk decision that actually matters, and it is what
        # kills m5.xlarge at 0.0013 -- then rank the survivors on capacity
        # per dollar, breaking exact ties toward the LARGER machine for
        # the measured reason above. Ties here are real rather than
        # accidental: a c5.xlarge is two c5.larges at twice the price, so
        # equal efficiency is the correct answer and something else has to
        # decide.
        #
        # In THIS catalogue the filter never binds: c5.large and c5.xlarge
        # score 130.7 per dollar-hour against m5.xlarge's 97.1, so
        # c5.xlarge is chosen with or without it at every deadline in the
        # study (verified 2026-09-14). Under Table 9 the declared rates it
        # reads are also not the rates any VM is hibernated at -- every
        # spot VM faces kh/D. It guards other catalogues; it is not a
        # mechanism behind any reported result.
        SURVIVAL_FLOOR = 0.5      # more likely than not to still be there
        viable = [v for v in cands if survival(v) >= SURVIVAL_FLOOR]
        if not viable:
            viable = cands        # nothing is safe; fall back to all

        best = max(viable, key=lambda v: ((v.speed * v.vcpu_count)
                                          / v.cost_rate,
                                          v.speed * v.vcpu_count))
        return dict(vm_type=best.vm_type, speed=best.speed,
                    cost_rate=best.cost_rate, mem_gb=best.memory_gb,
                    hib_rate=best.hibernation_rate, vcpu=best.vcpu_count)

    def _create_spot_vm(self, ready_time):
        """Provision one spot VM of the pool-resolved type."""
        t = self._spot_tpl
        return self._create_vm(t["vm_type"], t["speed"], t["cost_rate"],
                               t["mem_gb"], t["hib_rate"], t["vcpu"],
                               ready_time=ready_time)

    # ── PREEMPTIVE PROVISIONING ───────────────────────────────────────────────

    def _run_primary_scheduler(self):
        """Run ILS then apply Theorem 1 to pre-provision replacements."""
        super()._run_primary_scheduler()
        self._preemptive_provision()

    def _preemptive_provision(self):
        """
        Theorem 1: for each spot VM v, provision one replacement of the
        pool-resolved template if expected reactive rescue cost exceeds
        proactive provisioning cost.

        HORIZON. P(v hibernates) is taken over one average task on v,
        1 - exp(-lambda_v * e_avg / s_v). It was once documented as
        1 - exp(-lambda_v * D), which the code never computed. On
        principle neither is exact: C_reactive prices re-running all n_v
        tasks, so the matching exposure is v's own planned busy period,
        which lies between one task and D. The one-task horizon is the
        lower bound -- it understates the chance a rescue is needed, so it
        provisions no more than the exact form would -- and it is kept
        because any longer horizon can only add provisioning, and would
        add it through a declared rate this study calls illustrative.

        SENSITIVITY, measured on the post-fix-9 code (variant thm1_D,
        experiments/thm1_rb_variants.txt): with the horizon at D nothing
        changes at DF 0.5 / 1.0 or at n=100, but at DF=2.0 n=300
        R-BurstHADS becomes 27-51% faster and 2-25% cheaper. The switch is
        c5's declared 0.04/hr rate crossing PREEMPTIVE_RISK_THRESHOLD once
        the horizon exceeds ~4616 s, after which replacements are also
        bought for c5 VMs. Behaviour at DF=2.0 with n >= 200 therefore
        depends on that illustrative rate and on this horizon choice.

        DECLARED RATES. lambda_v is the per-type rate from main.py, not
        the scenario's kh/D. Under Table 9 every spot VM is hibernated at
        kh/D, so this test makes the same decision in every scenario: it
        fires for the three m5.xlarge (P ~0.22) and for no c5 VM
        (P ~0.001). Switching it off makes R-BurstHADS slower and more
        expensive in most cells (experiments/diag_rb_provisioning.*), but
        what triggers it is the illustrative m5.xlarge rate, not a risk
        the experiment instantiates.
        """
        if not self.all_tasks:
            return

        n_tasks = len(self.all_tasks)
        e_avg   = sum(t.exec_time for t in self.all_tasks) / n_tasks
        if not self._od_catalogue:
            return
        od_tpl  = self._od_catalogue[0]     # cheapest on-demand type (E3)
        od_rate = od_tpl["cost_rate"]

        for vm in list(self.spot_vms):
            if vm.hibernation_rate <= 0:
                continue

            p_hib = vm.hibernation_probability(e_avg / vm.speed)
            if p_hib < PREEMPTIVE_RISK_THRESHOLD:
                continue

            # Tasks assigned to this VM by ILS
            if self.solution:
                n_v = sum(1 for vid in self.solution.allocation.values()
                          if vid == vm.id)
            else:
                n_v = n_tasks // max(1, len(self.spot_vms))

            # Theorem 1 cost comparison.
            #
            # Both rate terms are costs PER UNIT OF WORK, so each must be
            # divided by that machine's WHOLE-MACHINE throughput,
            # speed * vcpu_count -- not by speed alone. Dividing by speed
            # is the same normalisation error Equation 8's WRR weight
            # originally carried: it prices a 4-vCPU machine as though it
            # retired one core's worth of work.
            #
            # It mattered here in a way that was invisible until the
            # provisioning template changed. c5.large and c5.xlarge have
            # identical cost per unit of work, 2.125e-6 $/work-unit, as
            # they must, being the same silicon at twice the size and
            # twice the price. Under the old expression they read 4.25e-6
            # and 8.5e-6 -- a factor of two apart purely because one has
            # more cores. So switching the template to c5.xlarge halved
            # c_reactive and doubled c_proactive at the same time, making
            # the test roughly four times harder to pass, and preemptive
            # provisioning silently switched itself off. Measured at
            # n=60, kh=5, kr=5: R-BurstHADS provisioned nothing and its
            # result became bit-identical to Burst-HADS.
            #
            # The hardcoded od_rate/2 was the same mistake with a literal
            # instead of a field: 2 was the on-demand VM's per-core speed,
            # written in when every VM in the pool had vcpu_count 1.
            s_rate   = self._spot_tpl["cost_rate"]
            s_speed  = self._spot_tpl["speed"]
            theta_s  = s_speed * self._spot_tpl["vcpu"]

            theta_od = od_tpl["speed"] * od_tpl["vcpu"]

            # C_proactive is the OVERHEAD of buying early, which this
            # module's own Theorem 1 states as
            #
            #     C_proactive = T_startup * r_s + epsilon
            #
            # The code used to add `e_avg/s_speed * s_rate` in place of
            # epsilon: the full cost of executing one average task on the
            # replacement. That is not an overhead. The work has to run
            # somewhere no matter what is decided here, and C_reactive is
            # already a DIFFERENCE between running it on on-demand and
            # running it on spot -- so pricing an absolute execution cost
            # against a differential benefit compares two different
            # quantities. The added term was also 2.6x the startup term,
            # so it dominated every decision it appeared in.
            #
            # Measured at n=60, kh=5, kr=5: m5.xlarge cleared the risk
            # threshold at p_hib = 0.228 and p*C_reactive = 1.64e-3, then
            # lost to an inflated C_proactive of 2.79e-3 against a
            # specified 7.65e-4. Preemptive provisioning never fired and
            # R-BurstHADS's output was bit-identical to Burst-HADS's.
            #
            # This restores the documented expression.
            #
            # It does not price the replacement's idle time, and that
            # omission was once recorded as the cause of R-BurstHADS's
            # cost premium over HADS in sc1 (kh=1), on the reasoning that
            # a replacement is billed from boot whether or not the
            # hibernation it anticipates arrives. Measured, the premise
            # does not hold: the replacements are 68-86% utilised in sc1
            # (busy / billed core-seconds), most of it through Algorithm 5
            # work stealing, and switching this test off makes
            # R-BurstHADS slower AND more expensive in every sc1 cell
            # (experiments/diag_rb_provisioning.*,
            # diag_rb_replacement_use.*). An idle-time term would only
            # provision less, in the direction that measures worse on
            # both axes, so it is deliberately not added.
            EPSILON = 0.0
            c_reactive  = n_v * e_avg * (od_rate/theta_od - s_rate/theta_s)
            c_proactive = STARTUP_LATENCY * s_rate + EPSILON

            if p_hib * c_reactive <= c_proactive:
                continue

            # Instance limits apply to this scheduler's own launches too.
            if not self._launches.can_launch_type("spot",
                                                  self._spot_tpl["vm_type"]):
                continue

            replacement = self._create_spot_vm(
                ready_time=STARTUP_LATENCY,  # ready before hibernation fires
            )
            self.provisioned_vms.append(replacement)

    # ── SCHEDULE OVERRIDE ─────────────────────────────────────────────────────

    def schedule(self, current_time):
        """
        Flush pending provision events.
        Respond to pool saturation after hibernation events.
        """
        super().schedule(current_time)

        if self.event_engine and self._pending_provision_events:
            for event in self._pending_provision_events:
                self.event_engine.add_event(event)
            self._pending_provision_events.clear()

        if current_time > 0 and self.event_engine:
            if current_time != self._last_saturation_response_time:
                self._respond_to_saturation(current_time)

    # ── THEOREM 2: ADAPTIVE VM COUNT ─────────────────────────────────────────

    def _respond_to_saturation(self, current_time):
        """
        Theorem 2 (revised): provision the minimum capacity that still
        makes the deadline, sized by _vms_needed_for_deadline().

        The original rule provisioned enough VMs that each held at most
        TASKS_PER_VM_CAP tasks, bounding makespan to
        t_hib + TASKS_PER_VM_CAP * avg_exec / speed. That bound is
        deadline-independent, so it bought capacity whether or not the
        deadline needed it -- see _vms_needed_for_deadline for the
        measured cost of that and for the replacement derivation.
        """
        # Count currently hibernated spot VMs
        n_now_hibernated = sum(
            1 for v in self.spot_vms
            if v.state in (VM.HIBERNATED, VM.TERMINATED)
        )

        # New hibernation detected if count increased
        if n_now_hibernated > self._n_hibernated_vms:
            self._n_hibernated_vms   = n_now_hibernated
            self._saturation_handled = False  # allow response to new event

        # Only respond ONCE per saturation event
        if self._saturation_handled:
            return

        # Only act when pool is actually saturated (all spot VMs down)
        active_spot = [v for v in self.spot_vms
                       if v.state not in (VM.HIBERNATED, VM.TERMINATED)]
        if len(active_spot) >= len(self.spot_vms):
            return

        # Mark handled before doing any work
        self._saturation_handled = True

        # Tasks queued on provisioned VMs (rescued tasks only)
        all_queued = []
        for vm in self.provisioned_vms:
            if vm.state not in (VM.HIBERNATED, VM.TERMINATED):
                for task in vm.tasks:
                    if not task.completed:
                        all_queued.append(task)

        slack    = self.D - current_time
        use_spot = slack > STARTUP_LATENCY * SLACK_MULTIPLIER
        # Fix 21: a burstable launched now boots for STARTUP_LATENCY as well.
        startup  = STARTUP_LATENCY

        active_prov = [v for v in self.provisioned_vms
                       if v.state not in (VM.HIBERNATED, VM.TERMINATED)]

        n_extra = self._vms_needed_for_deadline(
            all_queued, current_time, active_prov, use_spot, startup)
        n_extra = min(MAX_VMS_PER_EVENT, n_extra)

        if n_extra <= 0:
            return

        # Collect queued (non-running) tasks to redistribute -- a
        # multi-core VM can legitimately have vcpu_count tasks
        # RUNNING at once, so "queued" means everything beyond that,
        # not just index 1 onward.
        tasks_to_move = []
        for vm in active_prov:
            waiting = [t for t in vm.tasks if t not in vm.running]
            if waiting:
                for t in waiting:
                    vm.tasks.remove(t)
                    vm.release_memory(t)
                tasks_to_move.extend(waiting)

        if not tasks_to_move:
            return

        # Provision new VMs (the loop below stops at the instance limit;
        # if nothing could be launched, the waiting tasks go back where
        # they came from via the normal redistribution over active_prov)
        new_vms = []
        for _ in range(n_extra):
            if use_spot:
                if not self._launches.can_launch_type(
                        "spot", self._spot_tpl["vm_type"]):
                    break
                new_vm = self._create_spot_vm(
                    ready_time=current_time + STARTUP_LATENCY,
                )
            else:
                if not self._launches.can_launch_type("ondemand", BURST_TYPE):
                    break
                new_vm = self._create_vm(
                    BURST_TYPE, BURST_SPEED, BURST_RATE,
                    BURST_MEM_GB, 0.0, BURST_VCPU,
                    ready_time=current_time + STARTUP_LATENCY,   # fix 21
                    extra_credits=BURST_CREDITS_INIT,
                    baseline_fraction=BURST_BASELINE_FRAC,
                )
            new_vms.append(new_vm)
            self.provisioned_vms.append(new_vm)

        # Load-balanced distribution: longest tasks first, scored by
        # each target's real multi-core finish-time estimate rather
        # than a flat queue-time sum.
        all_targets = active_prov + new_vms
        tasks_to_move.sort(key=lambda t: t.remaining_time, reverse=True)

        for task in tasks_to_move:
            best_vm     = None
            best_finish = float('inf')
            for vm in all_targets:
                if vm.state in (VM.HIBERNATED, VM.TERMINATED):
                    continue
                if not vm.can_fit_task(task):
                    continue
                # Fix 17a: the same test tier 0 (_select_replacement_vm) and
                # Burst-HADS's migration apply -- memory, finish by D, CPU
                # credits for a burst-mode burstable, and the Section 3.4
                # spare-time margin for a spot target. The frozen code took
                # the earliest finish even when it lay past D; in the 104
                # runs that missed a deadline that placed 108 of the 109
                # missed tasks (experiments/diag_u10.txt).
                if not self._check_migration(task, vm, current_time, self.D,
                                             burst_mode=vm.is_burstable):
                    continue
                finish = vm.estimate_finish_time(task, current_time)
                if finish < best_finish:
                    best_finish = finish
                    best_vm     = vm
            if best_vm is None:
                # No provisioned target makes D: Algorithm 4's on-demand
                # attempt, as every other placement path ends, instead of a
                # placement known to be late.
                best_vm = self._attempt_ondemand_fallback(task, current_time)
            task.baseline_mode = False  # reactive rebalance -> burst mode
            best_vm.tasks.append(task)
            best_vm.reserve_memory(task)
            task.assigned_vm = best_vm
            if self.event_engine:
                best_vm.start_next_if_free(current_time, self.event_engine)


    # ── DEADLINE-AWARE SIZING ────────────────────────────────────────────────

    def _vms_needed_for_deadline(self, tasks, current_time, targets,
                                 use_spot, startup):
        """
        Theorem 2, revised: provision the MINIMUM capacity that makes the
        deadline, instead of a fixed queue-length cap.

        The original rule sized the fleet as ceil(n_queued / cap) with
        cap = 8 -- a constant fitted to this workload's mean task length
        and to the c5.xlarge speed (its own comment read "8 * 57s = 456s
        queue per VM at speed=4"). `self.D` entered only through
        `use_spot`, which chooses the instance TYPE, never how many. The
        trigger therefore fired identically whether the deadline was
        minutes or hours away, and R-BurstHADS bought capacity the
        deadline did not require. Measured at n=300 under pool
        saturation: 21 provisioned VMs, 76% of their billed seconds
        idle, and killing 17 of them changed makespan by 0.0% while
        cutting cost 40.7%.

        The sizing below is a work-conservation argument rather than a
        fitted constant. Let W be the remaining work of the tasks needing
        placement (task-seconds) and T the usable time left once a
        replacement has booted:

            T        = D - t_now - startup
            required = W / T
            deficit  = required - throughput(active targets)
            n_extra  = ceil(deficit / throughput(one new VM))

        Throughput is speed * vcpu_count -- the whole-instance measure,
        for the same reason Equation 8's numerator is whole-instance
        Gflops: a VM runs vcpu_count tasks concurrently, each at `speed`.

        A deficit of zero means the surviving fleet already finishes the
        queue before D, so nothing is bought. If the estimate proves
        optimistic -- list scheduling is not perfect and tasks are lumpy
        -- `_provision_one_more` still adds capacity per task later, and
        applies its own deadline test before doing so. That fallback is
        self-correcting, which is why no safety-margin fudge factor is
        applied here.
        """
        # W carries (1 + checkpoint_overhead), the factor execution charges
        # on every task, so W / T is the throughput the queue really needs.
        # Leaving it out is the planner error fix 8 removed from HADS and
        # Burst-HADS, here in this scheduler's own sizing.
        W = sum(t.remaining_time * (1.0 + t.checkpoint_overhead)
                for t in tasks if not t.completed)
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
            per_vm = BURST_SPEED * 1   # VM forces a burstable to one slot
        if per_vm <= 0:
            return 0

        return int(math.ceil(deficit / per_vm))

    # ── VM CREATION ──────────────────────────────────────────────────────────

    def _create_vm(self, vm_type, speed, cost_rate, mem_gb,
                   hib_rate, vcpu_count, ready_time, extra_credits=None,
                   baseline_fraction=None):
        """Create a VM and schedule its activation via ProvisioningEvent."""
        new_id = self._next_vm_id
        self._next_vm_id += 1

        market = (VM.BURSTABLE
                  if hib_rate == 0 and baseline_fraction is not None
                  else VM.SPOT)

        kwargs = dict(
            vm_id=new_id, vm_type=vm_type, market=market,
            speed=speed, cost_rate=cost_rate,
            memory_gb=mem_gb, hibernation_rate=hib_rate,
            vcpu_count=vcpu_count,
        )
        if baseline_fraction is not None:
            kwargs["baseline_fraction"] = baseline_fraction

        new_vm = VM(**kwargs)
        new_vm.state = VM.IDLE
        self._launches.commit(new_vm)
        new_vm.ready_time = ready_time     # fix 18: usable from ready_time
        new_vm._ready_event = True         # fix 21: its ProvisioningEvent starts the queue
        if extra_credits is not None:
            new_vm.cpu_credits = extra_credits

        prov_event = ProvisioningEvent(ready_time, new_vm, [], self)
        if self.event_engine:
            self.event_engine.add_event(prov_event)
        else:
            self._pending_provision_events.append(prov_event)

        return new_vm

    # ── select_vm ─────────────────────────────────────────────────────────────

    def select_vm(self, task, job, current_time):
        """
        R-BurstHADS's VM selection wraps the faithful, inherited
        Algorithm 4 procedure with two added tiers of its own:

        0. Pre-provisioned replacement spot VMs (Theorem 1) -- tried
           first since they exist specifically to pre-empt this
           rescue. These already served their startup latency and are
           running, so a task placed here starts immediately. Gated by
           the same _check_migration the baseline uses.
        1-2. Inherited from BurstHADS, unmodified: Algorithm 4
           Attempts 1-2 (idle burstable VM, then any active
           non-burstable VM) -- same priority order, same
           _check_migration deadline/credit tests as the baseline.
        3. Adaptive on-demand-avoidance provisioning (Theorem 2) --
           tried only once the inherited paper attempts are
           exhausted, so it never pre-empts Algorithm 4's own order.
           Creates a NEW VM: spot when the remaining slack exceeds
           SLACK_MULTIPLIER * STARTUP_LATENCY, the boot delay still
           leaves room and spot is within its launch limit, otherwise a
           burstable, which boots for STARTUP_LATENCY too (fix 21).
           Not interchangeable with tier 0: tier 0 is capacity that
           already exists, tier 3 is capacity that will not be usable
           for STARTUP_LATENCY seconds.
        4. Inherited from BurstHADS, unmodified: Algorithm 4 Attempt 3
           (last-resort on-demand).
        """
        vm = self._select_replacement_vm(task, current_time)
        if vm is not None:
            return vm

        vm = self._attempt_paper_migration(task, current_time)
        if vm is not None:
            return vm

        vm = self._provision_one_more(task, current_time)
        if vm is not None:
            return vm

        return self._attempt_ondemand_fallback(task, current_time)

    def _select_replacement_vm(self, task, current_time):
        """Tier 0 (R-BurstHADS's own contribution, not in the paper):
        pre-provisioned replacement spot VMs from Theorem 1.

        FAIRNESS FIX. This used to test only can_fit_task() plus a flat
        `estimate_finish_time <= D`, bypassing _check_migration entirely.
        That exempted R-BurstHADS's OWN provisioned spot VMs from the
        Section 3.4 spare-time rule ("the spare time has to be greater
        than the execution time of the longest task scheduled to vmj"),
        which BurstHADS's Attempt 2 enforces on every spot target it
        considers. The effect was a rule asymmetry on exactly the class
        of machine this scheduler's contribution rests on: tasks could
        be stacked onto a provisioned spot VM with zero reserve left to
        re-migrate them if that VM was itself hibernated -- and these
        VMs are genuinely exposed to hibernation, via
        ProvisioningEvent._expose_to_spot_risk. Routing through
        _check_migration applies the identical memory, deadline, credit
        and spot-spare tests the baseline uses.
        """
        for vm in self.provisioned_vms:
            if vm.state in (VM.HIBERNATED, VM.TERMINATED):
                continue
            if self._check_migration(task, vm, current_time, self.D,
                                     burst_mode=vm.is_burstable):
                return vm
        return None

    def _provision_one_more(self, task, current_time):
        """Provision one more VM for a task that has no viable target.

        The reuse-an-existing-provisioned-VM loop that used to open this
        method was removed: it re-tested self.provisioned_vms with the
        exact conditions _select_replacement_vm had already applied to
        the same list moments earlier, and nothing between the two calls
        can add to that list or release memory on it (_attempt_paper_
        migration returning None means it placed nothing). It could
        never return non-None. Tier 0 is the single place provisioned
        VMs are reused.
        """
        slack = self.D - current_time

        # Try spot.
        #
        # _check_migration cannot be used here: the VM does not exist
        # yet, so the tests are written out against the template, each
        # charging the STARTUP_LATENCY the new VM boots for (fix 21 for
        # the burstable).
        # The two tests it would have applied are therefore written out
        # against the template. The second is the Section 3.4 spot
        # spare-time rule, previously missing on this path for the same
        # reason tier 0 was missing it -- a brand-new spot VM carries no
        # queued work, so "the longest task scheduled to vmj including
        # ti" is just ti itself.
        #
        # Both finish predictions carry (1 + checkpoint_overhead), the
        # factor execution charges, as estimate_finish_time does (fix 8
        # removed the same omission from the baselines' planners). The
        # spare-time margin keeps exec_time / speed, as
        # BurstHADS._check_migration does for the paper's rule.
        ovh = 1.0 + task.checkpoint_overhead
        if slack > STARTUP_LATENCY * SLACK_MULTIPLIER:
            spot_speed = self._spot_tpl["speed"]
            finish     = (current_time + STARTUP_LATENCY
                          + task.remaining_time / spot_speed * ovh)
            spare      = self.D - finish
            longest    = task.exec_time / spot_speed
            if (finish <= self.D and spare > longest
                    and self._launches.can_launch_type(
                        "spot", self._spot_tpl["vm_type"])):
                vm = self._create_spot_vm(
                    ready_time=current_time + STARTUP_LATENCY,
                )
                self.provisioned_vms.append(vm)
                return vm

        # Try burstable
        # Fix 21: the burstable boots for STARTUP_LATENCY too.
        if ((current_time + STARTUP_LATENCY + task.remaining_time / BURST_SPEED * ovh) <= self.D
                and self._launches.can_launch_type("ondemand", BURST_TYPE)):
            vm = self._create_vm(
                BURST_TYPE, BURST_SPEED, BURST_RATE,
                BURST_MEM_GB, 0.0, BURST_VCPU,
                ready_time=current_time + STARTUP_LATENCY,   # fix 21
                extra_credits=BURST_CREDITS_INIT,
                baseline_fraction=BURST_BASELINE_FRAC,
            )
            self.provisioned_vms.append(vm)
            return vm

        return None

    # ── REPORTING ─────────────────────────────────────────────────────────────

    def provisioning_summary(self):
        n_spot  = sum(1 for v in self.provisioned_vms if v.market == VM.SPOT)
        n_burst = sum(1 for v in self.provisioned_vms if v.market == VM.BURSTABLE)
        return {
            "n_provisioned": len(self.provisioned_vms),
            "n_spot":        n_spot,
            "n_burstable":   n_burst,
        }
