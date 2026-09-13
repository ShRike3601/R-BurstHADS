from models.vm import VM


def start_execution(vms, current_time, event_engine):
    """
    Kick off execution across all VMs at simulation start.

    Billing is NOT started here unconditionally. A VM only starts
    being billed the instant it is actually handed a task to run
    (see VM.start_next_if_free) -- matching the paper's own framing
    of the spot/burstable/on-demand pools as VMs you SELECT and
    LAUNCH, not machines that are already running by default.
    Reserve burstable/on-demand VMs the initial solution never
    touches stay unbilled until something (a reactive migration,
    work stealing, proactive burst allocation) actually uses them.

    This also fills every VM's free execution slots via the
    centralized multi-core dispatch (vm.start_next_if_free), so a VM
    with vcpu_count > 1 starts that many tasks in parallel instead of
    just one -- a 4-vCPU VM behaves like four workers, not one fast
    sequential one.
    """
    for vm in vms:
        if vm.state in (VM.HIBERNATED, VM.TERMINATED):
            continue

        for task in vm.tasks:
            if task.memory_req > 0 and vm._queued_memory_mb == 0:
                vm.reserve_memory(task)

        vm.start_next_if_free(current_time, event_engine)

        if not vm.tasks:
            # Only start an idle-termination clock on a VM that has
            # actually been deployed (billed) at some point. A
            # reserve VM that was never launched isn't "idle" in the
            # billing sense -- it was never running -- so don't burn
            # it out of the pool for a hibernation rescue that might
            # need it later.
            if (vm.state == VM.IDLE and vm.ac_termination_time is None
                    and vm.is_deployed):
                from simulation.allocation_cycle_event import AllocationCycleEvent
                vm.start_ac(current_time)
                ac_event = AllocationCycleEvent(
                    vm.ac_termination_time, vm,
                    event_engine.scheduler
                )
                event_engine.add_event(ac_event)
