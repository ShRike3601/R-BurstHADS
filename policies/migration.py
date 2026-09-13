def migrate_task(task, job, vms, current_time, scheduler):
    
    vm = scheduler.select_vm(task, job, current_time)

    if vm:
        vm.tasks.append(task)
        task.assigned_vm = vm