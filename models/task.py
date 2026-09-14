class Task:
    def __init__(self, task_id, job_id, stage_id, exec_time,
                 memory_req=None):
        self.task_id = task_id
        self.id = task_id

        self.job_id = job_id
        self.stage_id = stage_id

        # Core timing
        self.exec_time = exec_time          # raw workload units (seconds on speed=1 VM)
        self.remaining_time = exec_time     # decreases as task executes

        # Memory requirement in MB (paper: 2.85-13.19 MB)
        self.memory_req = memory_req if memory_req is not None else 5.0

        # Deadline (assigned from stage)
        self.deadline = None

        # Scheduling
        self.assigned_vm = None
        self.last_migration_time = 0

        # Execution state
        self.current_event = None
        self.start_time = None
        self.finish_time = None
        self.completed = False

        # Checkpoint state
        # exec_start_on_current_vm: simulation time when task started
        # executing on its current VM (reset on each migration)
        self.exec_start_on_current_vm = None

        # How much work was saved at last checkpoint
        # remaining_time is reduced to this on hibernation recovery
        self.checkpointed_remaining = None

        # Checkpoint overhead fraction (paper: ovh = 0.10)
        self.checkpoint_overhead = 0.10

        # Priority (used by MD-BurstHADS for EDF ordering)
        self.priority = 0.0

        # True while this task is running in BASELINE mode on a
        # burstable VM (set by the work-stealing procedure --
        # Algorithm 5). Baseline mode earns CPU credits instead
        # of spending them; burst mode (hibernation-rescue
        # migrations) spends them. Irrelevant on non-burstable VMs.
        self.baseline_mode = False

    def apply_checkpoint_overhead(self):
        """
        Returns effective execution time including checkpoint overhead.
        Paper: total checkpoint overhead <= ovh * exec_time
        We add this overhead once when a task first executes.
        On restart from checkpoint, overhead is already baked in
        via remaining_time reduction.
        """
        return self.remaining_time * (1.0 + self.checkpoint_overhead)

    def save_checkpoint(self, current_time):
        """
        Record how much work has been completed up to current_time.
        Called just before a hibernation migration.
        exec_start_on_current_vm must be set when task began executing.
        """
        if self.exec_start_on_current_vm is not None and self.assigned_vm:
            elapsed = current_time - self.exec_start_on_current_vm
            work_done = elapsed * self.assigned_vm.speed
            # Fix 19: execution runs a task at speed / (1 + overhead)
            # (VM.start_next_if_free charges the overhead on the whole
            # remaining time), so that is the progress made. Crediting
            # elapsed * speed over-credited 0.49% / 0.71% / 0.79% of the
            # workload for HADS / Burst-HADS / R-BurstHADS
            # (experiments/diag_overcredit_boot.txt).
            work_done /= (1.0 + self.checkpoint_overhead)
            self.checkpointed_remaining = max(
                0.0,
                self.remaining_time - work_done
            )
        else:
            # No checkpoint possible — task restarts fully
            self.checkpointed_remaining = self.remaining_time

    def restore_from_checkpoint(self):
        """
        After migration, restore remaining_time from checkpoint.
        If no checkpoint exists, task runs from full remaining_time.
        """
        if self.checkpointed_remaining is not None:
            self.remaining_time = self.checkpointed_remaining
        # Reset exec tracking for new VM
        self.exec_start_on_current_vm = None