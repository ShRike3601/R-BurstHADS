def flatten_and_assign_deadlines(jobs):
    all_tasks = []

    for job in jobs:
        for stage in job.stages:
            for task in stage.tasks:
                task.stage_id = stage.stage_id
                task.deadline = stage.deadline
                all_tasks.append(task)

    return all_tasks