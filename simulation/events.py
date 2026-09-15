from models.vm import VM


class TaskCompleteEvent:
    def __init__(self, time, task, vm, engine):
        self.time   = time
        self.task   = task
        self.vm     = vm
        self.engine = engine

    def execute(self):
        # Guard: superseded events (task migrated elsewhere)
        if self.task.current_event != self:
            return
        if self.task.completed:
            return

        # Update CPU credits for burstable VM.
        # baseline_mode (set explicitly by proactive burst allocation
        # and by the work-stealing procedure, Algorithm 5) always
        # EARNS credits. Otherwise: burst mode -- spends credits --
        # whenever the task was migrated here after a hibernation
        # rescue (indicated by checkpointed_remaining being set) or
        # is running on a burstable VM by any other reactive path.
        if self.vm.is_burstable and self.task.exec_start_on_current_vm is not None:
            elapsed = self.time - self.task.exec_start_on_current_vm
            if getattr(self.task, "baseline_mode", False):
                self.vm.earn_credits(elapsed)
            elif self.task.checkpointed_remaining is not None:
                self.vm.consume_credits(elapsed)
            else:
                self.vm.earn_credits(elapsed)

        # Mark task complete
        self.task.finish_time = self.time
        self.task.completed   = True

        # Release memory on the VM
        self.vm.release_memory(self.task)

        if self.task in self.vm.tasks:
            self.vm.tasks.remove(self.task)
        if self.task in self.vm.running:
            self.vm.running.remove(self.task)

        # Fill any execution slot(s) this completion just freed up --
        # this is what makes a vcpu_count > 1 VM actually run several
        # tasks concurrently instead of one at a time.
        self.vm.start_next_if_free(self.time, self.engine)

        if self.vm.tasks:
            self.vm.state = VM.BUSY
        else:
            self.vm.state = VM.IDLE
            self._schedule_ac_termination()

        # Work stealing (only when supported and enabled)
        # Algorithm 5 trigger, per the paper: "It is triggered when a
        # hibernated spot VM resumes or when a VM (spot or on-demand)
        # becomes idle." Idle-triggered, unconditionally -- NOT gated on a
        # hibernation having already happened.
        #
        # The removed `_hibernation_occurred` condition suppressed every
        # steal until the first interruption fired. Under Table 9's sc1
        # (kh=1 over the whole run) that is most of the execution, so
        # Burst-HADS's tail-shortening mechanism was switched off for the
        # bulk of the makespan it is supposed to be shortening.
        if (hasattr(self.engine.scheduler, "slack") and
                getattr(self.engine.scheduler,
                        "enable_work_stealing", True)):
            from policies.work_stealing import work_stealing
            idle_vm  = self.vm
            busy_vms = [v for v in self.engine.scheduler.vms
                        if v.tasks and v.state not in
                        (VM.HIBERNATED, VM.TERMINATED)]
            work_stealing(
                idle_vm, busy_vms,
                self.engine.scheduler.jobs,
                self.time,
                self.engine.scheduler,
            )

        # Check stage completion (MD-BurstHADS)
        self._check_stage_completion()

        # Trigger dynamic rescheduling
        self.engine.scheduler.schedule(self.time)

        # Shut the fleet down once the bag is empty.
        self._release_fleet_if_done()

    def _release_fleet_if_done(self):
        """Terminate every surviving VM the instant the last task finishes.

        Without this, a machine stays deployed -- and billed -- until its
        900-second Allocation Cycle expires, so every scheduler pays a
        900s idle tail on every VM it still holds at the end of the run.
        Measured on the n=40 trace, that tail was roughly three quarters
        of every reported cost figure, and it punished the scheduler that
        FINISHED EARLIEST hardest: R-BurstHADS completed in 798s against
        HADS's 1583s and then idled a large fleet for a further 1887s.

        Releasing capacity the moment there is no work left is what an
        operator actually does, and it is applied identically to all
        three schedulers, so it is a property of the billing model rather
        than an advantage handed to any one of them. The Allocation Cycle
        still governs idle termination DURING a run, which is its job;
        this only covers the end of the run, which it never did well.
        """
        sched = self.engine.scheduler
        for job in sched.jobs:
            for stage in job.stages:
                for t in stage.tasks:
                    if not t.completed:
                        return

        for vm in sched.vms:
            if vm.state == VM.TERMINATED:
                continue
            if vm.state == VM.HIBERNATED:
                # Billing already stopped at the hibernation instant, but
                # the VM must still be retired here or it stays eligible
                # to RESUME after the job is over. ResumeEvent calls
                # start_billing unconditionally, so a machine coming back
                # at t > makespan opened a fresh billing interval, sat
                # idle with no work left to steal, and was closed by its
                # own 900-second AC timer: a closed interval lying
                # entirely beyond the end of the job, which the cost
                # metric then charged in full.
                #
                # This punished finishing early, and in exact proportion
                # -- the sooner a scheduler finished, the more of the
                # remaining resume events landed after its makespan. On
                # the kr>0 cells it cost HADS 6.1% and R-BurstHADS 21.4%,
                # and it was the entirety of R-BurstHADS's apparent +2.0%
                # cost penalty in sc5. ResumeEvent's own guard
                # (state != HIBERNATED -> return) does the rest.
                vm.state = VM.TERMINATED
                vm.ac_termination_time = None
                continue
            vm.stop_billing(self.time)
            vm.state = VM.TERMINATED
            vm.ac_termination_time = None

    def _schedule_ac_termination(self):
        """Schedule an AllocationCycleEvent for this VM."""
        from simulation.allocation_cycle_event import AllocationCycleEvent
        self.vm.start_ac(self.time)
        ac_event = AllocationCycleEvent(
            self.vm.ac_termination_time, self.vm, self.engine.scheduler
        )
        self.engine.add_event(ac_event)

    def _check_stage_completion(self):
        """Notify MD-BurstHADS when all tasks in a stage finish."""
        scheduler = self.engine.scheduler
        if not hasattr(scheduler, "on_stage_complete"):
            return
        task = self.task
        for job in scheduler.jobs:
            for stage in job.stages:
                if task in stage.tasks:
                    if all(t.completed for t in stage.tasks):
                        scheduler.on_stage_complete(job, stage, self.time)
                    return


class HibernationEvent:
    """
    Spot VM hibernates: memory+context saved to EBS.
    All running/queued tasks are checkpointed and migrated.
    VM transitions to HIBERNATED state.

    Paper: EC2 saves VM instance memory and context in EBS root volume.
    During interruption, user is only charged for EBS storage.
    """
    def __init__(self, time, vm, scheduler, resume_time=None):
        self.time        = time
        self.vm          = vm
        self.scheduler   = scheduler
        self.resume_time = resume_time   # if set, schedule a ResumeEvent

    def execute(self):
        from simulation.resume_event import ResumeEvent

        if self.vm.state in (VM.TERMINATED, VM.HIBERNATED):
            return

        self.vm.state = VM.HIBERNATED
        # Real-AWS billing: only EBS storage is charged during
        # hibernation, not compute time -- close the running-time
        # billing interval.
        self.vm.stop_billing(self.time)
        if hasattr(self.scheduler, '_hibernation_occurred'):
            self.scheduler._hibernation_occurred = True

        # Cancel AC timer if running (VM is no longer idle)
        self.vm.ac_termination_time = None

        # Collect unfinished tasks
        tasks_to_migrate = [t for t in self.vm.tasks if not t.completed]
        self.vm.tasks.clear()
        self.vm.running.clear()
        self.vm._queued_memory_mb = 0.0  # all tasks migrated away

        for task in tasks_to_migrate:
            # Save checkpoint before migration
            task.save_checkpoint(self.time)

            # Invalidate old event
            task.current_event = None
            # Every hibernation rescue is a burst-mode landing per
            # Algorithm 4 (spends credits on a burstable destination,
            # full speed) -- never baseline mode, which is reserved
            # for proactive burst allocation and work stealing.
            task.baseline_mode = False

            job    = self.scheduler.jobs[task.job_id]
            new_vm = self.scheduler.select_vm(task, job, self.time)

            if new_vm is None:
                print(f"[WARNING] No VM for task {task.id} "
                      f"after hibernation at t={self.time:.1f}")
                continue

            # Restore from checkpoint (remaining_time reduced)
            task.restore_from_checkpoint()

            # Assign to new VM — check memory
            if not new_vm.can_fit_task(task):
                # Try next best VM
                fallback = self._find_vm_with_memory(task)
                if fallback:
                    new_vm = fallback
                else:
                    print(f"[WARNING] No VM with memory for task {task.id}")
                    continue

            new_vm.tasks.append(task)
            new_vm.reserve_memory(task)
            task.assigned_vm = new_vm

            # Centralized multi-core dispatch: fills a free slot on
            # new_vm if one exists now, otherwise the task waits in
            # queue for one to free up.
            new_vm.start_next_if_free(self.time, self.scheduler.event_engine)

        # Schedule resume event if resume_time is set
        if self.resume_time is not None:
            resume_event = ResumeEvent(
                self.resume_time, self.vm, self.scheduler
            )
            self.scheduler.event_engine.add_event(resume_event)

        self.scheduler.schedule(self.time)

    def _find_vm_with_memory(self, task):
        """Fallback: find any active VM with enough memory."""
        for vm in self.scheduler.vms:
            if (vm.state not in (VM.HIBERNATED, VM.TERMINATED) and
                    vm.can_fit_task(task)):
                return vm
        return None


class TerminationEvent:
    """
    Spot VM is permanently terminated (not hibernated).
    Paper: cloud provider warns user 2 minutes before termination.
    Tasks cannot be recovered — they must restart from scratch.

    Difference from HibernationEvent:
    - No checkpoint restoration (tasks restart fully)
    - No resume possible
    - VM enters TERMINATED state permanently
    """
    def __init__(self, time, vm, scheduler):
        self.time      = time
        self.vm        = vm
        self.scheduler = scheduler

    def execute(self):
        if self.vm.state == VM.TERMINATED:
            return

        self.vm.state = VM.TERMINATED
        self.vm.stop_billing(self.time)
        self.vm.ac_termination_time = None

        tasks_to_migrate = [t for t in self.vm.tasks if not t.completed]
        self.vm.tasks.clear()
        self.vm.running.clear()
        self.vm._queued_memory_mb = 0.0

        for task in tasks_to_migrate:
            # NO checkpoint — task restarts from original exec_time
            task.remaining_time    = task.exec_time
            task.checkpointed_remaining = None
            task.current_event     = None
            task.exec_start_on_current_vm = None
            task.baseline_mode      = False  # rescue -> burst mode

            job    = self.scheduler.jobs[task.job_id]
            new_vm = self.scheduler.select_vm(task, job, self.time)

            if new_vm is None:
                print(f"[WARNING] No VM for terminated task {task.id} "
                      f"at t={self.time:.1f}")
                continue

            new_vm.tasks.append(task)
            new_vm.reserve_memory(task)
            task.assigned_vm = new_vm

            new_vm.start_next_if_free(self.time, self.scheduler.event_engine)

        self.scheduler.schedule(self.time)


class StageCompleteEvent:
    """Fired when all tasks in a stage finish. Triggers next stage."""
    def __init__(self, time, job, stage, scheduler):
        self.time      = time
        self.job       = job
        self.stage     = stage
        self.scheduler = scheduler

    def execute(self):
        self.scheduler.on_stage_complete(self.job, self.stage, self.time)


class VMReadyEvent:
    """Fix 21: a VM a scheduler launched becomes usable after its deploy time
    (STARTUP_LATENCY: TCC23's omega, the paper's T_start). It only starts the
    VM's queued tasks -- no scheduler call, no work stealing, no Allocation
    Cycle -- so the one thing it changes is when they start. R-BurstHADS's
    provisioned VMs are started by their ProvisioningEvent instead."""
    def __init__(self, time, vm, engine):
        self.time   = time
        self.vm     = vm
        self.engine = engine

    def execute(self):
        if self.vm.state in (VM.HIBERNATED, VM.TERMINATED):
            return
        self.vm.start_next_if_free(self.time, self.engine)
