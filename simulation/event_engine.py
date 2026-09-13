class EventEngine:
    def __init__(self, scheduler):
        self.time = 0
        self.events = []
        self.scheduler = scheduler

    def add_event(self, event):
        self.events.append(event)

    def run(self):
        while self.events:

            # sort events by time
            self.events.sort(key=lambda e: e.time)

            # get earliest event
            event = self.events.pop(0)

            # move time forward
            self.time = event.time

            # execute event
            event.execute()

            # 🔥 call scheduler after every event
            if hasattr(self.scheduler, "dynamic") and self.scheduler.dynamic:
                self.scheduler.schedule(self.time)