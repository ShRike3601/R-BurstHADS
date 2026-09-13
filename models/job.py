class Job:
    def __init__(self, job_id, stages):
        self.job_id = job_id
        self.stages = stages  # list of Stage objects