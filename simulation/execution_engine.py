from models.vm import VM


def start_execution(vms, current_time, event_engine):
    """
    Kick off execution across all VMs at simulation start.

    Billing is NOT started here. A VM is billed from the moment a
    scheduler launches it (LaunchCounter.commit, TCC23 section 3.1),
    whether or not it ever runs a task. Pool VMs no scheduler launches
    are never billed.

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
            # been launched (is billing). A reserve VM that was never
            # launched is not running, so it is not "idle".
            if (vm.state == VM.IDLE and vm.ac_termination_time is None
                    and vm.is_deployed):
                from simulation.allocation_cycle_event import AllocationCycleEvent
                vm.start_ac(current_time)
                ac_event = AllocationCycleEvent(
                    vm.ac_termination_time, vm,
                    event_engine.scheduler
                )
                event_engine.add_event(ac_event)
