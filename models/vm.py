class VM:
    # Market types
    SPOT      = "spot"
    BURSTABLE = "burstable"
    ONDEMAND  = "ondemand"

    # States
    IDLE       = "idle"
    BUSY       = "busy"
    HIBERNATED = "hibernated"
    TERMINATED = "terminated"

    # AWS T3.large credit parameters
    T3_CREDIT_EARN_RATE    = 36.0 / 3600.0   # credits per second at baseline
    T3_CREDIT_CONSUME_RATE = 1.0  / 60.0     # credits per second per vCPU in burst
    T3_MAX_CREDITS         = 144.0

    def __init__(self, vm_id, vm_type, market, speed, cost_rate,
                 memory_gb=4.0,
                 baseline_fraction=1.0,
                 credit_rate=0.0,
                 hibernation_rate=0.0,
                 vcpu_count=1):
        """
        hibernation_rate : lambda in hibernations-per-second. NOTE: the
                           values wired up in main.py (0.03-0.04/hr for
                           c5.large/c5.xlarge, 5/2700/s ~= 6.7/hr for
                           m5.xlarge) are NOT derived from AWS Spot
                           Advisor data -- an earlier version of this
                           docstring claimed they were; that claim was
                           checked against AWS's published interruption
                           frequency tables and does not hold (off by
                           4-5 orders of magnitude). m5.xlarge's rate
                           instead matches Teylo et al. (2023) Table 9's
                           sc2 (worst case): lambda = k/D with k=5,
                           D=2700s. c5.large/c5.xlarge's lower rate has
                           no equivalent in that paper -- Teylo et al.
                           do not differentiate hibernation risk by
                           instance type. That per-type differentiation
                           is this thesis's own extension, used to make
                           R-BurstHADS's risk-aware WRR weighting
                           observable; it is not a claim about measured
                           real-world AWS interruption-rate differences
                           between these instance types.
                           0.0 for burstable and on-demand VMs.

        vcpu_count : number of tasks this VM can run AT THE SAME TIME
                     (paper Constraint 4: "the number of parallel tasks
                     allocated to vm_j does not exceed nvc_j"). Real
                     spec per instance size (e.g. c5.large=2,
                     c5.xlarge=4). Burstable VMs are ALWAYS forced to 1
                     regardless of what's passed in, per the paper's
                     explicit rule (Section 3.2/3.4): a burstable VM
                     never holds more than one task at a time, no
                     matter its real core count -- that's a deliberate
                     stability/cost choice, not a hardware limit.
        """
        self.id               = vm_id
        self.vm_type          = vm_type
        self.market           = market
        self.speed            = speed
        self.cost_rate        = cost_rate
        self.memory_gb        = memory_gb
        self.memory_mb        = memory_gb * 1024.0
        self.baseline_fraction = baseline_fraction
        self.hibernation_rate  = hibernation_rate   # λ per second
        self.vcpu_count        = 1 if market == VM.BURSTABLE else max(1, vcpu_count)

        # CPU credits (burstable only)
        if market == VM.BURSTABLE:
            self.cpu_credits   = VM.T3_MAX_CREDITS
            self._earn_rate    = VM.T3_CREDIT_EARN_RATE
            self._consume_rate = VM.T3_CREDIT_CONSUME_RATE * speed
        else:
            self.cpu_credits   = None
            self._earn_rate    = 0.0
            self._consume_rate = 0.0

        self.state = VM.IDLE
        self.tasks   = []   # every not-yet-completed task assigned here
        self.running = []   # subset of `tasks` currently executing
                            # (len <= vcpu_count); the rest are waiting
                            # for a free execution slot.

        # Allocation Cycle (paper: AC = 900 seconds)
        self.allocation_cycle    = 900.0
        self.current_ac_start    = 0.0
        self.ac_termination_time = None

        # Memory tracking
        self._queued_memory_mb = 0.0

        # Billing intervals: [[start, end_or_None], ...]. Real-AWS
        # style billing -- charged for every second the VM is
        # deployed and not hibernated, whether or not it happens to
        # be executing a task at that instant. Closed on hibernation
        # or termination, reopened on resume.
        self._billing_intervals = []

    # ------------------------------------------------------------------
    # MARKET TYPE PROPERTIES
    # ------------------------------------------------------------------

    @property
    def is_spot(self):
        return self.market == VM.SPOT

    @property
    def is_burstable(self):
        return self.market == VM.BURSTABLE

    @property
    def is_ondemand(self):
        return self.market == VM.ONDEMAND

    @property
    def is_deployed(self):
        """
        True once this VM has actually been billed at least once --
        i.e. something has actually launched/used it, as opposed to
        sitting untouched in an elastic reserve pool (M^b/M^o) that
        was never drawn from. Used to avoid starting an
        Allocation-Cycle termination clock on a VM that was never
        really "running" in the first place.
        """
        return bool(self._billing_intervals)

    # ------------------------------------------------------------------
    # HIBERNATION RISK
    # ------------------------------------------------------------------

    def hibernation_probability(self, duration_seconds):
        """
        P(hibernation during duration) = 1 - e^(-λ × duration)
        Exponential distribution — standard model for Poisson processes.
        Returns 0.0 for non-spot VMs.
        """
        import math
        if self.hibernation_rate <= 0 or not self.is_spot:
            return 0.0
        return 1.0 - math.exp(-self.hibernation_rate * duration_seconds)

    # ------------------------------------------------------------------
    # SPEED
    # ------------------------------------------------------------------

    def effective_speed(self, burst_mode=False):
        if not self.is_burstable:
            return self.speed
        return self.speed if burst_mode else self.speed * self.baseline_fraction

    # ------------------------------------------------------------------
    # CPU CREDITS
    # ------------------------------------------------------------------

    def can_burst(self, required_credits):
        if not self.is_burstable:
            return True
        return self.cpu_credits is not None and self.cpu_credits >= required_credits

    def credits_required(self, exec_time_seconds):
        if not self.is_burstable:
            return 0.0
        return (exec_time_seconds / 60.0) * self.speed

    def consume_credits(self, elapsed_seconds):
        if not self.is_burstable or self.cpu_credits is None:
            return
        self.cpu_credits = max(
            0.0, self.cpu_credits - self._consume_rate * elapsed_seconds
        )

    def earn_credits(self, elapsed_seconds):
        if not self.is_burstable or self.cpu_credits is None:
            return
        self.cpu_credits = min(
            VM.T3_MAX_CREDITS,
            self.cpu_credits + self._earn_rate * elapsed_seconds
        )

    # ------------------------------------------------------------------
    # MEMORY
    # ------------------------------------------------------------------

    def available_memory_mb(self):
        return self.memory_mb - self._queued_memory_mb

    def can_fit_task(self, task):
        return self.available_memory_mb() >= task.memory_req

    def reserve_memory(self, task):
        self._queued_memory_mb += task.memory_req

    def release_memory(self, task):
        self._queued_memory_mb = max(
            0.0, self._queued_memory_mb - task.memory_req
        )

    # ------------------------------------------------------------------
    # MULTI-CORE EXECUTION (paper Constraint 4: up to vcpu_count tasks
    # run concurrently; extras wait for a free slot)
    # ------------------------------------------------------------------

    def estimate_finish_time(self, task, current_time, task_speed=None):
        """
        List-scheduling estimate of when `task` would finish if
        assigned to this VM right now, given whatever is already
        running or waiting here across its vcpu_count execution
        slots. This is what makes a 4-vCPU VM actually behave like
        four parallel workers instead of one fast one.
        """
        if task_speed is None:
            task_speed = self.speed

        # One "free-at" time per core. A running task's real finish
        # time is already sitting on its TaskCompleteEvent; unused
        # cores are free right now.
        free_at = []
        for t in self.running:
            free_at.append(t.current_event.time if t.current_event is not None
                           else current_time)
        while len(free_at) < self.vcpu_count:
            free_at.append(current_time)
        free_at.sort()

        # Waiting tasks ahead of the hypothetical new one, claimed in
        # order onto whichever core frees up soonest.
        # NOTE: the (1 + checkpoint_overhead) factor below must mirror
        # start_next_if_free exactly. That method charges checkpointing on
        # every execution; if this estimate omits it, every migration and
        # placement decision is optimistic by that factor, and whichever
        # scheduler packs closest to the deadline silently overshoots it.
        # Measured before this was aligned (n=300, pool saturation):
        # BurstHADS stopped opening on-demand VMs at 3, packed 86-94 tasks
        # onto each, and missed 8 deadlines, while HADS opened a 4th at ~76
        # tasks each and missed none -- an artefact of the estimator, not a
        # difference in the algorithms.
        waiting = [t for t in self.tasks if t not in self.running]
        for t in waiting:
            idx = free_at.index(min(free_at))
            speed = (self.effective_speed(
                        burst_mode=not getattr(t, "baseline_mode", False))
                     if self.is_burstable else self.speed)
            free_at[idx] = (max(free_at[idx], current_time)
                            + (t.remaining_time / speed)
                            * (1.0 + t.checkpoint_overhead))

        idx = free_at.index(min(free_at))
        start = max(current_time, free_at[idx])
        return start + ((task.remaining_time / task_speed)
                        * (1.0 + task.checkpoint_overhead))

    def start_next_if_free(self, current_time, engine):
        """
        Fill any free execution slot(s) with the next waiting task(s).
        Every place that hands this VM a task (initial execution,
        migration, work-stealing, resume) should call this afterward
        instead of hand-rolling its own "is a slot free" logic -- that
        keeps burst-vs-baseline speed and checkpoint-overhead handling
        consistent everywhere.
        """
        from simulation.events import TaskCompleteEvent

        while len(self.running) < self.vcpu_count:
            waiting = [t for t in self.tasks
                       if t not in self.running and not t.completed]
            if not waiting:
                break
            # Billing begins the instant a task actually starts
            # running here -- not at VM construction, not merely at
            # task assignment. Idempotent: a no-op if already billing.
            self.start_billing(current_time)
            task = waiting[0]
            self.running.append(task)

            if task.start_time is None:
                task.start_time = current_time
            task.exec_start_on_current_vm = current_time

            if self.is_burstable:
                speed = self.effective_speed(
                    burst_mode=not getattr(task, "baseline_mode", False))
            else:
                speed = self.speed

            exec_time = task.remaining_time / speed
            # Checkpointing is a STANDING cost while a task runs, not
            # something you stop paying once you have been interrupted.
            #
            # This previously read `if task.checkpointed_remaining is
            # None`, i.e. the 10% overhead was charged on a task's first,
            # undisturbed execution and then SKIPPED on every resume --
            # and checkpointed_remaining is non-None precisely when a
            # task is recovering from a hibernation. Recovery was
            # therefore strictly cheaper per unit of remaining work than
            # never having been interrupted at all. Combined with billing
            # stopping on hibernation (HibernationEvent.stop_billing,
            # which is faithful to the paper), that made being
            # interrupted a net BENEFIT in this simulator -- the
            # mechanism behind HADS finishing faster under failure than
            # on its own undisturbed baseline.
            exec_time *= (1.0 + task.checkpoint_overhead)

            finish_time = current_time + exec_time
            event = TaskCompleteEvent(finish_time, task, self, engine)
            task.current_event = event
            engine.add_event(event)

    # ------------------------------------------------------------------
    # BILLING (real-AWS style: charged for the whole deployed period,
    # not just the seconds a task happens to be executing)
    # ------------------------------------------------------------------

    def start_billing(self, current_time):
        if self._billing_intervals and self._billing_intervals[-1][1] is None:
            return  # an interval is already open
        self._billing_intervals.append([current_time, None])

    def stop_billing(self, current_time):
        if self._billing_intervals and self._billing_intervals[-1][1] is None:
            self._billing_intervals[-1][1] = current_time

    def billed_seconds(self, sim_end_time):
        total = 0.0
        for start, end in self._billing_intervals:
            total += (end if end is not None else sim_end_time) - start
        return total

    # ------------------------------------------------------------------
    # ALLOCATION CYCLE
    # ------------------------------------------------------------------

    def start_ac(self, current_time):
        self.current_ac_start    = current_time
        self.ac_termination_time = current_time + self.allocation_cycle

    def ac_expired(self, current_time):
        return (self.ac_termination_time is not None and
                current_time >= self.ac_termination_time and
                self.state == VM.IDLE)

    def __repr__(self):
        credits = (f"{self.cpu_credits:.1f}"
                   if self.cpu_credits is not None else "N/A")
        return (f"VM(id={self.id}, type={self.vm_type}, "
                f"market={self.market}, speed={self.speed}, "
                f"vcpu={self.vcpu_count}, mem={self.memory_gb}GB, "
                f"λ={self.hibernation_rate:.2e}, "
                f"state={self.state}, credits={credits})")
