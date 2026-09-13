"""
ProactiveMigrationEvent: P-BurstHADS's core runtime contribution.

Fires periodically during simulation. For each task running on a
high-risk spot VM, computes:

  expected_hibernation_cost = P(hibernation) x (checkpoint_overhead
                               + rescue_cost_on_fallback_vm)

  proactive_migration_saving = expected_hibernation_cost
                               - proactive_migration_overhead

If saving > 0: migrate the task NOW to a safer VM while it's
still running smoothly, rather than waiting for hibernation to
force an emergency rescue.

Why this beats BurstHADS:
  BurstHADS waits for hibernation, then rescues tasks to
  burstable VMs at $0.0832/hr with checkpoint restart overhead.
  P-BurstHADS migrates early to cheap spot VMs at $0.031/hr
  with zero restart overhead (task continues from current progress).

Mathematical model:
  P(hibernation in remaining_time) = 1 - exp(-lambda x remaining_s)
  checkpoint_overhead              = remaining_time x ovh (default 10%)
  rescue_vm_cost_rate              = burstable or ondemand rate
  proactive_vm_cost_rate           = safe spot VM rate

  net_saving = P(hib) x (checkpoint_overhead x rescue_rate
               + remaining_time x (rescue_rate - proactive_rate))
               - migration_overhead_fraction x remaining_time x proactive_rate

  Migrate if net_saving > 0.
"""

import math
from models.vm import VM

# How often to check for proactive migration opportunities (simulated seconds)
CHECK_INTERVAL = 30.0

# Minimum remaining time for proactive migration to be worthwhile
# Tasks nearly done don't benefit from early migration
MIN_REMAINING_FOR_MIGRATION = 20.0

# Migration overhead as fraction of remaining execution time
# Small one-time cost to hand task off to new VM
MIGRATION_OVERHEAD_FRACTION = 0.02   # 2% of remaining execution time


class ProactiveMigrationEvent:
    """
    Periodic event that checks all tasks on high-risk VMs and
    proactively migrates them when expected hibernation cost
    exceeds migration cost.

    Only fires for schedulers that have the proactive_migration
    attribute set to True (i.e., P-BurstHADS, not BurstHADS).
    """

    def __init__(self, time, scheduler):
        self.time      = time
        self.scheduler = scheduler

    def execute(self):
        """
        For each task running on a high-risk spot VM:
          1. Compute P(hibernation during remaining execution)
          2. Compute expected cost of reactive rescue
          3. Compute cost of proactive migration now
          4. If proactive migration saves money, migrate immediately
        """
        engine = self.scheduler.event_engine
        if engine is None:
            return

        # Only fire if scheduler supports proactive migration
        if not getattr(self.scheduler, "proactive_migration", False):
            return

        migrations_done = 0

        for vm in self.scheduler.vms:
            if not vm.is_spot:
                continue
            if vm.hibernation_rate <= 0:
                continue
            if vm.state in (VM.HIBERNATED, VM.TERMINATED):
                continue
            if not vm.tasks:
                continue

            # Check each task queued on this VM
            tasks_to_migrate = []
            for task in list(vm.tasks):
                if task.completed:
                    continue

                # Compute remaining execution time on this VM
                if task.exec_start_on_current_vm is not None:
                    elapsed = self.time - task.exec_start_on_current_vm
                    work_done = elapsed * vm.speed
                    remaining_s = max(
                        0.0,
                        task.remaining_time - work_done
                    ) / vm.speed
                else:
                    remaining_s = task.remaining_time / vm.speed

                if remaining_s < MIN_REMAINING_FOR_MIGRATION:
                    continue   # task almost done, not worth migrating

                # P(hibernation during remaining execution)
                p_hib = 1.0 - math.exp(
                    -vm.hibernation_rate * remaining_s
                )

                if p_hib < 0.01:
                    continue   # less than 1% risk, skip

                # Find best safe migration target
                safe_vm = self._find_safe_vm(task, vm)
                if safe_vm is None:
                    continue

                # Expected cost of reactive rescue (if we do nothing)
                # = P(hib) × (checkpoint_restart_overhead + rescue_on_burstable)
                rescue_rate = self._get_rescue_rate()
                checkpoint_overhead_cost = (
                    remaining_s * task.checkpoint_overhead * rescue_rate
                )
                rescue_execution_cost = remaining_s * rescue_rate
                expected_reactive_cost = p_hib * (
                    checkpoint_overhead_cost + rescue_execution_cost
                )

                # Cost of proactive migration now
                # = small handoff overhead + execution on safe VM
                migration_overhead_cost = (
                    remaining_s * MIGRATION_OVERHEAD_FRACTION
                    * safe_vm.cost_rate
                )
                proactive_execution_cost = (
                    (remaining_s * vm.speed / safe_vm.speed)
                    * safe_vm.cost_rate
                )
                total_proactive_cost = (
                    migration_overhead_cost + proactive_execution_cost
                )

                # Current cost of staying (no hibernation case)
                stay_cost = remaining_s * vm.cost_rate

                # Net saving from proactive migration
                # = (stay_cost + expected_reactive_cost) - total_proactive_cost
                net_saving = (
                    stay_cost + expected_reactive_cost
                    - total_proactive_cost
                )

                if net_saving > 0:
                    tasks_to_migrate.append((task, safe_vm, net_saving))

            # Execute migrations, highest saving first
            tasks_to_migrate.sort(key=lambda x: x[2], reverse=True)
            for task, safe_vm, saving in tasks_to_migrate:
                self._migrate_task(task, vm, safe_vm, engine)
                migrations_done += 1

        # Schedule next check ONLY if tasks still running
        all_done = all(
            t.completed
            for vm in self.scheduler.vms
            for t in vm.tasks
        ) and all(
            t.completed
            for job in self.scheduler.jobs
            for stage in job.stages
            for t in stage.tasks
        )
        if not all_done:
            next_event = ProactiveMigrationEvent(
                self.time + CHECK_INTERVAL, self.scheduler
            )
            engine.add_event(next_event)

    def _find_safe_vm(self, task, current_vm):
        """
        Find the best safe VM to migrate this task to.
        Safe = spot VM with hibernation_rate < current VM's rate AND
               enough capacity and deadline slack.
        Prefer cheapest safe VM with available capacity.
        """
        best_vm    = None
        best_score = float('inf')

        for vm in self.scheduler.spot_vms:
            if vm.id == current_vm.id:
                continue
            if vm.state in (VM.HIBERNATED, VM.TERMINATED):
                continue
            if not vm.can_fit_task(task):
                continue
            # Must be safer than current VM
            if vm.hibernation_rate >= current_vm.hibernation_rate:
                continue

            # Check deadline feasibility
            queue_time = sum(
                t.remaining_time / vm.speed for t in vm.tasks
            )
            remaining_work = task.remaining_time / vm.speed
            finish = self.time + queue_time + remaining_work
            if finish > self.scheduler.D:
                continue

            # Score: lower cost rate preferred
            score = vm.cost_rate
            if score < best_score:
                best_score = score
                best_vm    = vm

        return best_vm

    def _get_rescue_rate(self):
        """
        Cost rate of reactive rescue VM (burstable or on-demand).
        Used to estimate cost of NOT migrating proactively.
        """
        burstable = [v for v in self.scheduler.vms if v.is_burstable]
        if burstable:
            return min(v.cost_rate for v in burstable)
        ondemand = [v for v in self.scheduler.vms if v.is_ondemand]
        if ondemand:
            return min(v.cost_rate for v in ondemand)
        return 0.085 / 3600  # fallback: c5.large on-demand rate

    def _migrate_task(self, task, src_vm, dst_vm, engine):
        """
        Perform proactive migration of task from src_vm to dst_vm.

        Unlike hibernation recovery:
        - Task saves progress (checkpoint) before migration
        - Task resumes from checkpointed progress on new VM
        - No restart overhead — seamless handoff
        - src_vm continues running its other tasks
        """
        from simulation.events import TaskCompleteEvent

        # Save checkpoint at current progress
        task.save_checkpoint(self.time)

        # Cancel current event on src_vm
        task.current_event = None

        # Remove from src_vm queue
        if task in src_vm.tasks:
            src_vm.tasks.remove(task)
            src_vm.release_memory(task)

        # Restore from checkpoint
        task.restore_from_checkpoint()

        # Assign to destination VM
        dst_vm.tasks.append(task)
        dst_vm.reserve_memory(task)
        task.assigned_vm = dst_vm

        # Fire execution event on new VM if task is first in queue
        if dst_vm.tasks[0] is task:
            if task.start_time is None:
                task.start_time = self.time
            task.exec_start_on_current_vm = self.time
            exec_time  = task.remaining_time / dst_vm.speed
            finish_time = self.time + exec_time
            event = TaskCompleteEvent(
                finish_time, task, dst_vm, engine
            )
            task.current_event = event
            engine.add_event(event)

        # Chain on src_vm for next task if queue not empty
        if src_vm.tasks:
            next_task = src_vm.tasks[0]
            if next_task.current_event is None:
                if next_task.start_time is None:
                    next_task.start_time = self.time
                next_task.exec_start_on_current_vm = self.time
                exec_time  = next_task.remaining_time / src_vm.speed
                finish_time = self.time + exec_time
                event = TaskCompleteEvent(
                    finish_time, next_task, src_vm, engine
                )
                next_task.current_event = event
                engine.add_event(event)
