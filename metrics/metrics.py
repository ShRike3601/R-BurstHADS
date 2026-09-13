class Metrics:

    def __init__(self, jobs, vms):
        self.jobs = jobs
        self.vms = vms

    def makespan(self):
        max_time = 0

        for job in self.jobs:
            for stage in job.stages:
                for task in stage.tasks:
                    if task.finish_time and task.finish_time > max_time:
                        max_time = task.finish_time

        return max_time

    def deadline_misses(self):
        misses = 0

        for job in self.jobs:
            for stage in job.stages:
                for task in stage.tasks:
                    if task.finish_time and task.finish_time > task.deadline:
                        misses += 1

        return misses

    def total_cost(self):
        """
        Real-AWS-style billing: each VM is charged for every second it
        was actually deployed -- from launch to hibernation/
        termination, or to the end of the simulation if it was never
        shut down -- not just the seconds it happened to be executing
        a task. This replaces the old per-task-execution-time cost
        model, which undercounted every VM that ever sat idle while
        still deployed (exactly the situation Allocation-Cycle
        idle-termination and CPU-credit accrual both depend on being
        billed for).

        ONE rule for every VM: launch to genuine shutdown.

        The previous version passed sim_end = self.makespan(), which
        reads as "stop the meter when the job is done" but only ever
        applied to billing intervals still OPEN at the end.
        VM.billed_seconds keeps a CLOSED interval's own recorded end
        whatever that is, so a single cost number mixed three rules: a
        hibernated VM billed to the hibernation instant (correct), a VM
        shut down by the 900-second idle timer billed well past the end
        of the job, and a VM still alive at the end clamped back to the
        makespan. Which rule a machine fell under depended on whether it
        happened to be holding an idle tail, and burstable VMs are
        exempt from the idle timer, so they were consistently judged
        under the strictest rule while everything else got the loosest.

        sim_end is now the true end of the simulation, the latest moment
        any VM was still deployed, so an open interval is billed to the
        same horizon as a closed one. With
        TaskCompleteEvent._release_fleet_if_done shutting the fleet down
        as the last task finishes, that horizon normally IS the
        makespan; the difference is that it now arrives there by
        measurement rather than by clamping.
        """
        closed = [e for vm in self.vms
                  for _s, e in vm._billing_intervals if e is not None]
        sim_end = max(closed + [self.makespan()])
        return sum(vm.cost_rate * vm.billed_seconds(sim_end)
                   for vm in self.vms)

    def summary(self):
        return {
            "makespan": self.makespan(),
            "deadline_misses": self.deadline_misses(),
            "total_cost": round(self.total_cost(), 6),
        }
