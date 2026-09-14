"""
Adoption patch for fixes 18, 19 and 20, mirroring variants._boot(True),
variants._checkpoint(True) and variants._u10(True) statement for statement.
Fix 17a is applied separately by experiments/fix17_adopt_patch.py --a.

Usage: python fix18_20_adopt_patch.py PROJECT_ROOT
Every replacement must match exactly once; on any mismatch nothing is written.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
edits = {}


def rep(path, old, new):
    edits.setdefault(path, []).append((old, new))


# ── fix 18: boot delay of VMs R-BurstHADS provisions ──
rep("models/vm.py",
    """        self._billing_intervals = []
""",
    """        self._billing_intervals = []

        # Fix 18: when this VM becomes usable. None for a VM usable on
        # creation; RBurstHADS._create_vm sets it for the VMs it provisions,
        # whose ProvisioningEvent fires at this time.
        self.ready_time = None
""")
rep("models/vm.py",
    """        if task_speed is None:
            task_speed = self.speed

        # One "free-at" time per core.""",
    """        if task_speed is None:
            task_speed = self.speed

        # Fix 18: nothing can start on this VM before it is ready.
        if self.ready_time is not None and current_time < self.ready_time:
            current_time = self.ready_time

        # One "free-at" time per core.""")
rep("models/vm.py",
    """        from simulation.events import TaskCompleteEvent

        while len(self.running) < self.vcpu_count:""",
    """        from simulation.events import TaskCompleteEvent

        # Fix 18: a provisioned VM starts nothing before it is ready; its
        # ProvisioningEvent calls this again at ready_time. Tasks used to
        # start at once on a spot VM still booting: 6,661 early starts, 26.9 s
        # early on average, all on R-BurstHADS's VMs
        # (experiments/diag_overcredit_boot.txt).
        if self.ready_time is not None and current_time < self.ready_time:
            return

        while len(self.running) < self.vcpu_count:""")
rep("scheduler/r_burst_hads.py",
    """        new_vm = VM(**kwargs)
        new_vm.state = VM.IDLE
        self._launches.commit(new_vm)
""",
    """        new_vm = VM(**kwargs)
        new_vm.state = VM.IDLE
        self._launches.commit(new_vm)
        new_vm.ready_time = ready_time     # fix 18: usable from ready_time
""")

# ── fix 19: a checkpoint credits executed progress ──
rep("models/task.py",
    """            elapsed = current_time - self.exec_start_on_current_vm
            work_done = elapsed * self.assigned_vm.speed
""",
    """            elapsed = current_time - self.exec_start_on_current_vm
            work_done = elapsed * self.assigned_vm.speed
            # Fix 19: execution runs a task at speed / (1 + overhead)
            # (VM.start_next_if_free charges the overhead on the whole
            # remaining time), so that is the progress made. Crediting
            # elapsed * speed over-credited 0.49% / 0.71% / 0.79% of the
            # workload for HADS / Burst-HADS / R-BurstHADS
            # (experiments/diag_overcredit_boot.txt).
            work_done /= (1.0 + self.checkpoint_overhead)
""")

# ── fix 20: U10, overhead in the on-demand fallback's deadline test ──
for path in ("scheduler/hads.py", "scheduler/burst_hads.py"):
    rep(path,
        """            finish = (current_time + STARTUP_LATENCY
                      + task.remaining_time / probe.speed)
""",
        """            # Fix 20 (U10): execution charges (1 + overhead) on every task.
            finish = (current_time + STARTUP_LATENCY
                      + task.remaining_time / probe.speed
                      * (1.0 + task.checkpoint_overhead))
""")

out = {}
for path, pairs in edits.items():
    p = root / path
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"MISMATCH {path} ({n} matches):\n{old[:200]}")
        text = text.replace(old, new)
    out[p] = text
for p, text in out.items():
    p.write_text(text, encoding="utf-8")
print(f"fixes 18, 19, 20 applied: {sum(len(v) for v in edits.values())} edits in {len(out)} files")
