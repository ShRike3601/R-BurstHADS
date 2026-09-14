"""
AllocationCycleEvent: fires when an idle VM reaches the end of its
Allocation Cycle (AC).

Paper behavior (Section 3.3):
- Time is divided into AC units (paper uses AC = 900 seconds)
- A VM that reaches the end of AC_cur in IDLE state is terminated
- This prevents billing for VMs that are sitting idle
- Busy VMs are not terminated — their AC resets when they become idle
- Burstable VMs are explicitly exempt (Section 3.3: "Non-burstable
  idle vmj") — they're kept around across idle gaps for their CPU
  credit balance, not torn down and rebuilt.

In our simulation:
- AC = 900 seconds (paper value)
- When a VM becomes idle, the timer is armed for the end of the cycle it
  is in, cycles counted over its billed uptime (VM.start_ac)
- If still idle at the end of that cycle → TERMINATED
- If it receives a task before then → the timer is ignored
"""

from models.vm import VM


class AllocationCycleEvent:
    def __init__(self, time, vm, scheduler):
        self.time      = time
        self.vm        = vm
        self.scheduler = scheduler

    def execute(self):
        # Only terminate if VM is still idle AND this is still the
        # current AC (guard against re-activation).
        #
        # `vm.state` alone is not a reliable busy/idle signal in this
        # simulator -- it only ever flips to HIBERNATED, TERMINATED,
        # or back to IDLE when a queue empties; nothing sets it to
        # BUSY when a task is appended (migration and work-stealing
        # both just push onto vm.tasks directly). So a VM that
        # started an AC timer while briefly idle, then received new
        # queued work before the timer fired, would still read
        # state == IDLE here and get wiped out mid-queue -- tasks and
        # all, via the vm.tasks.clear() below. `vm.tasks` is what the
        # rest of the codebase actually treats as ground truth for
        # busy/idle, so check that too.
        if self.vm.state != VM.IDLE or self.vm.tasks:
            return

        # Paper Section 3.3: idle-termination only applies to
        # non-burstable VMs. A burstable VM keeps its CPU credit
        # balance and standing availability across idle gaps.
        if self.vm.is_burstable:
            return

        # Check this event matches the VM's current AC termination time
        # (guards against stale events from a previous AC cycle)
        if (self.vm.ac_termination_time is None or
                abs(self.time - self.vm.ac_termination_time) > 0.001):
            return

        # Terminate the VM
        self.vm.state = VM.TERMINATED
        self.vm.stop_billing(self.time)
        self.vm.tasks.clear()
        self.vm.running.clear()
        self.vm.ac_termination_time = None

        # Remove from scheduler's available pools if scheduler tracks them
        if hasattr(self.scheduler, "_remove_terminated_vm"):
            self.scheduler._remove_terminated_vm(self.vm)
