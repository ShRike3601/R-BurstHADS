"""
Adoption patch for fix 21 (experiments/fix21_plan.md), mirroring
variants._f21(True, True, True) statement for statement.

Usage: python fix21_adopt_patch.py PROJECT_ROOT
Every replacement must match exactly once; on any mismatch nothing is written.

Two places are written more explicitly than the variant, with the same numbers:
  - the Phase-3 / Phase (c) probe VM carries ready_time = STARTUP_LATENCY
    (_fresh_probe) where the variant recognised the probe by its id of -1;
  - _launch_burstable_vms sets ready_time = STARTUP_LATENCY unconditionally;
    the variant set it only in the primary schedule, the only place the
    method is called (experiments/diag_launch21_base.txt: no other launch site).
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
edits = {}
appends = {}


def rep(path, old, new):
    edits.setdefault(path, []).append((old, new))


# ── VM: ready event for any launched VM handed a task while booting ─────────
rep("models/vm.py",
    """        self.ready_time = None
""",
    """        self.ready_time = None
        # Fix 21: True once something will start this VM's queue at
        # ready_time -- a VMReadyEvent, or R-BurstHADS's ProvisioningEvent.
        self._ready_event = False
""")
rep("models/vm.py",
    """        # Fix 18: a provisioned VM starts nothing before it is ready; its
        # ProvisioningEvent calls this again at ready_time. Tasks used to
        # start at once on a spot VM still booting: 6,661 early starts, 26.9 s
        # early on average, all on R-BurstHADS's VMs
        # (experiments/diag_overcredit_boot.txt).
        if self.ready_time is not None and current_time < self.ready_time:
            return
""",
    """        # Fixes 18 and 21: a VM a scheduler launched starts nothing before it
        # is ready. R-BurstHADS's provisioned VMs are started at ready_time by
        # their ProvisioningEvent; any other VM handed a task while booting
        # gets a VMReadyEvent that only starts its queue. Tasks used to start
        # at once on R-BurstHADS's spot VMs still booting (fix 18,
        # experiments/diag_overcredit_boot.txt) and on every other VM a
        # scheduler launched (fix 21, experiments/diag_launch21_base.txt).
        if self.ready_time is not None and current_time < self.ready_time:
            if engine is not None and not self._ready_event:
                from simulation.events import VMReadyEvent
                self._ready_event = True
                engine.add_event(VMReadyEvent(self.ready_time, self, engine))
            return
""")
appends["simulation/events.py"] = ('class VMReadyEvent', '''

class VMReadyEvent:
    """Fix 21: a VM a scheduler launched becomes usable after its deploy time
    (STARTUP_LATENCY: TCC23's omega, the paper's T_start). It only starts the
    VM's queued tasks -- no scheduler call, no work stealing, no Allocation
    Cycle -- so the one thing it changes is when they start. R-BurstHADS's
    provisioned VMs are started by their ProvisioningEvent instead."""
    def __init__(self, time, vm, engine):
        self.time   = time
        self.vm     = vm
        self.engine = engine

    def execute(self):
        if self.vm.state in (VM.HIBERNATED, VM.TERMINATED):
            return
        self.vm.start_next_if_free(self.time, self.engine)
''')

# ── HADS and Burst-HADS: the parts common to both ───────────────────────────
BOOT_HELPERS = '''
    def _boot_offset(self, vm):
        """Fix 21: when `vm` can start work, measured from the primary
        schedule's t = 0. The builder's VMs are usable at once; a VM this
        scheduler launches (or a probe standing for one) waits STARTUP_LATENCY."""
        return vm.ready_time if vm.ready_time is not None else 0.0

    def _fresh_probe(self, tpl):
        """Fix 21: a not-yet-launched VM of type `tpl` as the primary schedule
        would launch it, usable only after STARTUP_LATENCY."""
        probe = make_vm(tpl, -1)
        probe.ready_time = STARTUP_LATENCY
        return probe

'''
LAUNCH_OLD = """        new_vm.state = VM.IDLE

        self.ondemand_vms.append(new_vm)
"""
LAUNCH_NEW = """        new_vm.state = VM.IDLE
        # Fix 21: a VM this scheduler launches waits its deploy time, at t = 0
        # in the primary schedule as much as mid-run.
        new_vm.ready_time = current_time + STARTUP_LATENCY

        self.ondemand_vms.append(new_vm)
"""
CAPPED_OLD = """        fit = [v for v in cands if v.can_fit_task(task)]
        if fit or cands:
            vm = min(fit or cands,
                     key=lambda v: v.estimate_finish_time(task, current_time))
            self._launches.commit(vm)
            return vm
"""
CAPPED_NEW = """        fit = [v for v in cands if v.can_fit_task(task)]
        if fit or cands:
            pool = fit or cands
            # Fix 21: a pool VM never launched is launched here, mid-run, so it
            # is judged -- and, if chosen, runs -- after its deploy time.
            fresh = [v for v in pool if not self._launches.is_launched(v)]
            for v in fresh:
                v.ready_time = current_time + STARTUP_LATENCY
            vm = min(pool, key=lambda v: v.estimate_finish_time(task, current_time))
            for v in fresh:
                if v is not vm:
                    v.ready_time = None
            self._launches.commit(vm)
            return vm
"""
for path in ("scheduler/hads.py", "scheduler/burst_hads.py"):
    rep(path, "        return max(cores) if cores else 0.0\n",
        "        return (max(cores) if cores else 0.0) + self._boot_offset(vm)\n")
    rep(path, "if self._check_schedule(task, make_vm(t, -1), vm_tasks,",
        "if self._check_schedule(task, self._fresh_probe(t), vm_tasks,")
    rep(path, LAUNCH_OLD, LAUNCH_NEW)
    rep(path, CAPPED_OLD, CAPPED_NEW)
rep("scheduler/hads.py",
    """    # ------------------------------------------------------------------
    # SCHEDULE ENTRY POINT
    # ------------------------------------------------------------------

    def schedule(self, current_time):""",
    """""" + BOOT_HELPERS.lstrip("\n") + """    # ------------------------------------------------------------------
    # SCHEDULE ENTRY POINT
    # ------------------------------------------------------------------

    def schedule(self, current_time):""")

# ── Burst-HADS only ──────────────────────────────────────────────────────────
rep("scheduler/burst_hads.py",
    """    def _solution_task_finish_times(self, solution):""",
    BOOT_HELPERS.lstrip("\n") + """    def _solution_task_finish_times(self, solution):""")
rep("scheduler/burst_hads.py",
    """            cores = [0.0] * vm.vcpu_count
            for t in tasks:
                idx = cores.index(min(cores))
                cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
                finish[t] = cores[idx]
""",
    """            off = self._boot_offset(vm)      # fix 21
            cores = [0.0] * vm.vcpu_count
            for t in tasks:
                idx = cores.index(min(cores))
                cores[idx] += (t.exec_time / vm.speed) * (1.0 + t.checkpoint_overhead)
                finish[t] = cores[idx] + off
""")
rep("scheduler/burst_hads.py",
    """        return (task.exec_time / sp) * (1.0 + task.checkpoint_overhead)
""",
    """        return (task.exec_time / sp) * (1.0 + task.checkpoint_overhead) + self._boot_offset(burst_vm)
""")
rep("scheduler/burst_hads.py",
    """            new_vm.state = VM.IDLE

            self.burstable_vms.append(new_vm)
""",
    """            new_vm.state = VM.IDLE
            # Fix 21: a burstable this scheduler launches waits its deploy
            # time. Algorithm 1 Part 2 launches them in the primary schedule,
            # at t = 0; the builder's pool only seeds the type.
            new_vm.ready_time = STARTUP_LATENCY

            self.burstable_vms.append(new_vm)
""")
rep("scheduler/burst_hads.py",
    """        for vm in candidates:
            if (self._launches.can_launch(vm)
                    and self._check_migration(task, vm, current_time, deadline)):
                self._launches.commit(vm)
                return vm
""",
    """        for vm in candidates:
            if not self._launches.can_launch(vm):
                continue
            # Fix 21: a pool VM this run has not launched would be launched
            # here, mid-run, so the test charges its deploy time.
            fresh = not self._launches.is_launched(vm)
            if fresh:
                vm.ready_time = current_time + STARTUP_LATENCY
            if self._check_migration(task, vm, current_time, deadline):
                self._launches.commit(vm)
                return vm
            if fresh:
                vm.ready_time = None
""")

# ── R-BurstHADS: 21b and its ProvisioningEvent flag ─────────────────────────
rep("scheduler/r_burst_hads.py",
    """        new_vm.ready_time = ready_time     # fix 18: usable from ready_time
""",
    """        new_vm.ready_time = ready_time     # fix 18: usable from ready_time
        new_vm._ready_event = True         # fix 21: its ProvisioningEvent starts the queue
""")
rep("scheduler/r_burst_hads.py",
    """        startup  = STARTUP_LATENCY if use_spot else 0.0
""",
    """        # Fix 21: a burstable launched now boots for STARTUP_LATENCY as well.
        startup  = STARTUP_LATENCY
""")
rep("scheduler/r_burst_hads.py",
    """                new_vm = self._create_vm(
                    BURST_TYPE, BURST_SPEED, BURST_RATE,
                    BURST_MEM_GB, 0.0, BURST_VCPU,
                    ready_time=current_time,
""",
    """                new_vm = self._create_vm(
                    BURST_TYPE, BURST_SPEED, BURST_RATE,
                    BURST_MEM_GB, 0.0, BURST_VCPU,
                    ready_time=current_time + STARTUP_LATENCY,   # fix 21
""")
rep("scheduler/r_burst_hads.py",
    """        if ((current_time + task.remaining_time / BURST_SPEED * ovh) <= self.D
""",
    """        # Fix 21: the burstable boots for STARTUP_LATENCY too.
        if ((current_time + STARTUP_LATENCY + task.remaining_time / BURST_SPEED * ovh) <= self.D
""")
rep("scheduler/r_burst_hads.py",
    """            vm = self._create_vm(
                BURST_TYPE, BURST_SPEED, BURST_RATE,
                BURST_MEM_GB, 0.0, BURST_VCPU,
                ready_time=current_time,
""",
    """            vm = self._create_vm(
                BURST_TYPE, BURST_SPEED, BURST_RATE,
                BURST_MEM_GB, 0.0, BURST_VCPU,
                ready_time=current_time + STARTUP_LATENCY,   # fix 21
""")

# ── documentation that fix 21 made false (no behaviour) ─────────────────────
rep("scheduler/r_burst_hads.py",
    """VM TYPE SELECTION:
  Spot VMs if:     slack > STARTUP_LATENCY * SLACK_MULTIPLIER
  Burstable VMs if: deadline too tight for spot startup
""",
    """VM TYPE SELECTION (tier 3, _provision_one_more):
  Spot VM if slack > STARTUP_LATENCY * SLACK_MULTIPLIER, it finishes by D
  with the Section 3.4 spare-time margin, and its type is within its
  launch limit; otherwise a burstable if it finishes by D. Both boot for
  STARTUP_LATENCY (fix 21). This docstring used to say a burstable is
  chosen when the deadline is too tight for spot startup; measured, that
  never selected one, before fix 21 or after: the spot launch limit chose
  1,401 of the 1,453 burstables and the spare-time rule 52
  (experiments/diag_launch21_f21.txt, 7,200 runs).
""")
rep("scheduler/r_burst_hads.py",
    """           Creates a NEW VM: spot when the remaining slack exceeds
           SLACK_MULTIPLIER * STARTUP_LATENCY and the boot delay still
           leaves room, otherwise a burstable, which is ready at once.
""",
    """           Creates a NEW VM: spot when the remaining slack exceeds
           SLACK_MULTIPLIER * STARTUP_LATENCY, the boot delay still
           leaves room and spot is within its launch limit, otherwise a
           burstable, which boots for STARTUP_LATENCY too (fix 21).
""")
rep("scheduler/r_burst_hads.py",
    """        # _check_migration cannot be used here: the VM does not exist
        # yet and estimate_finish_time() has no notion of a boot delay,
        # so it would understate the finish time by STARTUP_LATENCY.
""",
    """        # _check_migration cannot be used here: the VM does not exist
        # yet, so the tests are written out against the template, each
        # charging the STARTUP_LATENCY the new VM boots for (fix 21 for
        # the burstable).
""")
rep("simulation/provisioning_event.py",
    """response to a saturation event. After STARTUP_LATENCY seconds
(zero for burstable VMs, which paper Section 3 treats as always
on-demand-available), the VM is active and ready to receive tasks.
""",
    """response to a saturation event. After STARTUP_LATENCY seconds the VM
is active and ready to receive tasks -- a burstable too since fix 21: a t3
launched mid-run boots like any EC2 instance, and TCC23 Section 3's
availability statement concerns revocation, not readiness.
""")
rep("simulation/provisioning_event.py",
    """# Pre-provisioned VM startup time (seconds)
# Represents time to configure and start a spot instance
# that was requested at scheduling time
STARTUP_LATENCY = 45.0
""",
    """# Deploy time of a VM a scheduler launches (seconds): TCC23's omega, the
# paper's T_start. Every launched VM except the builder's initial fleet
# waits it before running a task (fixes 18 and 21).
STARTUP_LATENCY = 45.0
""")

out = {}
for path, pairs in edits.items():
    p = root / path
    text = out.get(p) or p.read_text(encoding="utf-8")
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"MISMATCH {path} ({n} matches):\n{old[:200]}")
        text = text.replace(old, new)
    out[p] = text
for path, (marker, block) in appends.items():
    p = root / path
    text = out.get(p) or p.read_text(encoding="utf-8")
    if marker in text:
        raise SystemExit(f"MISMATCH {path}: {marker} already present")
    out[p] = text.rstrip("\n") + "\n" + block
for p, text in out.items():
    p.write_text(text, encoding="utf-8")
print(f"fix 21 applied: {sum(len(v) for v in edits.values())} edits and {len(appends)} append in {len(out)} files")
