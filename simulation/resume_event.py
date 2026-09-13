"""
ResumeEvent: fires when a hibernated spot VM becomes available again.

In AWS, a hibernated spot instance resumes when spare capacity
becomes available at a price <= the user's max price.
The VM's memory and context are restored from EBS storage.

Paper behavior on resume:
- VM transitions from HIBERNATED to IDLE
- Work-stealing procedure is triggered to redistribute tasks
  from busy VMs onto the resumed VM
- The VM re-enters the scheduling pool

In our Poisson model:
- Resume events are scheduled at random times after hibernation
- Only hibernated VMs can resume

Billing: a resumed instance is "running" again from this moment,
whether or not it immediately gets handed a task -- same as any
freshly-launched VM, it's now subject to Allocation-Cycle
idle-termination if nothing shows up for it in time.
"""

from models.vm import VM


class ResumeEvent:
    def __init__(self, time, vm, scheduler):
        self.time      = time
        self.vm        = vm
        self.scheduler = scheduler

    def execute(self):
        # Only process if VM is still hibernated
        if self.vm.state != VM.HIBERNATED:
            return

        self.vm.state = VM.IDLE
        self.vm.start_billing(self.time)

        # CPU credits do NOT accumulate during hibernation -- they
        # were frozen when the hibernation event fired, and resume
        # normal earn/consume behavior from here on with no change
        # needed.

        # Trigger work stealing: try to give this VM useful work
        if hasattr(self.scheduler, "slack"):
            from policies.work_stealing import work_stealing
            busy_vms = [v for v in self.scheduler.vms
                        if v.tasks and v.state != VM.HIBERNATED
                        and v.state != VM.TERMINATED]
            work_stealing(
                self.vm,
                busy_vms,
                self.scheduler.jobs,
                self.time,
                self.scheduler,
            )

        # If nothing was stolen, this VM sits IDLE and its own AC
        # timer will start the next time a TaskCompleteEvent (or
        # this scheduler's own dispatch) notices it has no tasks --
        # for a resumed VM with truly nothing to do, schedule it here.
        if not self.vm.tasks and self.vm.ac_termination_time is None:
            from simulation.allocation_cycle_event import AllocationCycleEvent
            self.vm.start_ac(self.time)
            ac_event = AllocationCycleEvent(
                self.vm.ac_termination_time, self.vm, self.scheduler
            )
            self.scheduler.event_engine.add_event(ac_event)

        # Notify scheduler so it can reassign if needed
        self.scheduler.schedule(self.time)
