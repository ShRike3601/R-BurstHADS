class Stage:
    def __init__(self, stage_id, deadline, tasks):
        self.stage_id = stage_id
        self.deadline = deadline
        self.tasks = tasks  # list of Task objects