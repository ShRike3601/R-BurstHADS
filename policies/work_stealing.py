"""
Burst Work-Stealing Procedure -- Algorithm 5, Teylo et al. 2023,
Section 3.5.

Plain-language summary: whenever a VM finishes a task and has a free
execution slot, this looks at other VMs that still have a backlog and
moves some of their *not-yet-started* work onto that free slot, so it
isn't sitting unused while other VMs are still queued up. A VM with
vcpu_count cores can have up to vcpu_count tasks genuinely running at
once, so "has a free slot" means fewer tasks running than cores --
not simply "has zero tasks."

Rules taken directly from the paper (not our own invention):
  - Steal FROM expensive on-demand VMs before cheap spot VMs (line 1:
    "prioritizes non-burstable on-demand VMs") -- get tasks off the
    costly VMs first.
  - Only tasks still waiting in a VM's queue are eligible -- tasks
    actually running right now are never touched.
  - Every candidate steal is checked with the same feasibility test
    used by the migration procedure: does the destination have the
    memory, and will the task still make the deadline there?
  - If the destination is an idle BURSTABLE VM, the stolen task runs
    in BASELINE mode -- slower (baseline_fraction of full speed), but
    it EARNS CPU credits instead of spending them -- and the
    procedure stops after moving exactly ONE task there. The paper is
    explicit about this: queuing more than one task in baseline mode
    on a burstable VM would just slow the application down. (Every
    burstable VM's vcpu_count is forced to 1 anyway, so this is also
    just the general "destination has a free slot" rule applied to a
    single-core VM.)
  - If the destination is any other VM, stealing can keep going and
    pull more than one task in the same pass, up to however many
    free slots it has.
"""

from models.vm import VM


def work_stealing(idle_vm, busy_vms, jobs, current_time, scheduler):
    if idle_vm.state in (VM.HIBERNATED, VM.TERMINATED):
        return
    if len(idle_vm.running) >= idle_vm.vcpu_count:
        return  # no free execution slot to steal into
    if not hasattr(scheduler, "_check_migration") or not hasattr(scheduler, "D"):
        return  # scheduler doesn't support the Algorithm 4/5 feasibility test

    deadline = scheduler.D
    target_is_burstable = idle_vm.is_burstable

    # Line 1: sort_by_market(BR) -- steal from expensive on-demand VMs
    # before cheap spot VMs. Burstable VMs are never steal sources
    # (paper: "for each NON-burstable vm_j in BR"). A source needs a
    # genuine backlog: more queued tasks than it currently has running.
    sources = sorted(
        [v for v in busy_vms
         if v is not idle_vm and not v.is_burstable
         and len(v.tasks) > len(v.running)],
        key=lambda v: 0 if v.is_ondemand else 1
    )

    for src_vm in sources:
        # selectTasks(vm_j): only queued (not-yet-started) tasks are
        # eligible -- tasks actually running are left alone so we
        # never throw away in-progress work.
        stealable = [
            t for t in src_vm.tasks
            if t not in src_vm.running
            and not t.completed
            and current_time - t.last_migration_time >= 3
        ]

        for task in stealable:
            if not scheduler._check_migration(
                task, idle_vm, current_time, deadline, burst_mode=False
            ):
                continue

            _steal_task(task, src_vm, idle_vm, current_time, scheduler,
                        baseline_mode=target_is_burstable)

            if len(idle_vm.running) >= idle_vm.vcpu_count:
                # Destination is full -- also covers the paper's
                # "stop after one" rule for burstable destinations,
                # since those always have vcpu_count == 1.
                return


def _steal_task(task, src_vm, dst_vm, current_time, scheduler, baseline_mode):
    """Move `task` from src_vm's queue onto dst_vm and let the
    centralized dispatcher start it if a slot is free."""
    src_vm.tasks.remove(task)
    src_vm.release_memory(task)

    task.assigned_vm = dst_vm
    task.baseline_mode = baseline_mode
    task.last_migration_time = current_time
    dst_vm.tasks.append(task)
    dst_vm.reserve_memory(task)

    dst_vm.start_next_if_free(current_time, scheduler.event_engine)
