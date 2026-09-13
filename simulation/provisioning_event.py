"""
ProvisioningEvent: fires when a pre-provisioned VM (R-BurstHADS's own
Theorem 1 / Theorem 2 contribution) becomes active.

R-BurstHADS provisions replacement VMs at scheduling time or in
response to a saturation event. After STARTUP_LATENCY seconds
(zero for burstable VMs, which paper Section 3 treats as always
on-demand-available), the VM is active and ready to receive tasks.

Billing starts here, at activation (ready_time) -- NOT deferred
until the VM is actually handed a task. This is deliberate: Theorem
1's own cost model ("C_proactive = T_startup * r_s + epsilon")
explicitly counts the cost of having the replacement standing by,
whether or not it ends up used. That's the entire cost/benefit trade
R-BurstHADS's preemptive provisioning is weighing.
"""

import math

from models.vm import VM

# Pre-provisioned VM startup time (seconds)
# Represents time to configure and start a spot instance
# that was requested at scheduling time
STARTUP_LATENCY = 45.0


class ProvisioningEvent:
    def __init__(self, time, new_vm, rescue_tasks, scheduler):
        self.time         = time
        self.new_vm       = new_vm
        self.rescue_tasks = rescue_tasks
        self.scheduler    = scheduler

    def execute(self):
        engine = self.scheduler.event_engine
        vm     = self.new_vm

        # VM is now fully active and billing starts.
        vm.state = VM.IDLE
        vm.start_billing(self.time)

        # Add to scheduler pools so select_vm can use it -- filed
        # under its own actual market type. (Previously this always
        # added the VM to spot_vms regardless of market, which
        # silently miscounted a provisioned BURSTABLE VM as a spot
        # VM in every spot_vms-based saturation/risk calculation.)
        if vm not in self.scheduler.vms:
            self.scheduler.vms.append(vm)
        if vm not in self.scheduler.all_vms:
            self.scheduler.all_vms.append(vm)
        if vm.is_spot and vm not in self.scheduler.spot_vms:
            self.scheduler.spot_vms.append(vm)
        elif vm.is_burstable and vm not in self.scheduler.burstable_vms:
            self.scheduler.burstable_vms.append(vm)
        elif vm.is_ondemand and vm not in self.scheduler.ondemand_vms:
            self.scheduler.ondemand_vms.append(vm)

        # Assign any pre-queued rescue tasks
        for task in self.rescue_tasks:
            if task.completed:
                continue
            vm.tasks.append(task)
            vm.reserve_memory(task)
            task.assigned_vm = task.assigned_vm or vm

        # Centralized multi-core dispatch -- fills as many free
        # slots as vm.vcpu_count and queued tasks allow.
        vm.start_next_if_free(self.time, engine)

        # Trigger work stealing from new VM perspective. This pulls
        # tasks from overloaded VMs onto the newly available VM if it
        # has a free slot after the rescue tasks above.
        if len(vm.running) < vm.vcpu_count and hasattr(self.scheduler, 'slack'):
            try:
                from policies.work_stealing import work_stealing
                busy_vms = [v for v in self.scheduler.vms
                            if v.tasks
                            and v.state not in (VM.HIBERNATED, VM.TERMINATED)
                            and v.id != vm.id]
                if busy_vms:
                    work_stealing(
                        vm, busy_vms,
                        self.scheduler.jobs,
                        self.time,
                        self.scheduler,
                    )
            except Exception:
                pass  # work stealing is optional

        # A spot VM that just came online is exposed to interruption
        # for the rest of its life, exactly like a pool spot VM.
        self._expose_to_spot_risk()

        self.scheduler.schedule(self.time)

    def _expose_to_spot_risk(self):
        """
        Enter this VM into the paper's Poisson interruption process.

        Scripted scenario hibernations are bound to specific VM objects
        at t=0 (main.run_simulation), so a VM provisioned at t>0 was
        previously unreachable by any hibernation event -- R-BurstHADS's
        replacement fleet was structurally immune to the failure mode
        under study while still being priced and risk-rated as spot.

        Draw is inverse-CDF from Exponential(rate), the same lambda_h
        model the poisson_natural scenario uses. A VM whose draw lands
        past the deadline simply survives the run.

        TABLE 9 PARITY (2026-09-13). Under a Table 9 scenario every pool
        spot VM is hibernated by one process, lambda_h = kh/D with resume
        at lambda_r = kr/D, whatever its instance type (see the Table 9
        loop in main.run_simulation). A spot VM launched mid-run was
        instead drawn once, at its declared per-type rate, with no resume:
        for the c5.xlarge template that is 0.04/hr, between 12x and 750x
        below the kh/D faced by the identical c5.xlarge instances already
        in the pool across the checkpoint grid. The machines R-BurstHADS
        provisions were therefore safer than the same instance type in
        the same market, an asymmetry between it and the baselines. They
        now enter the identical process from the moment they are ready,
        so spot_risk_mode governs only scenarios without a Table 9 rate.
        """
        risk = getattr(self.scheduler, "_spot_risk", None)
        vm   = self.new_vm
        if not risk or not vm.is_spot:
            return

        table9 = risk.get("table9")
        if table9 is not None:
            engine = self.scheduler.event_engine
            if engine is None:
                return
            from simulation.events import HibernationEvent
            kh, kr = table9
            D      = risk["deadline"]
            lam_h  = kh / D
            lam_r  = (kr / D) if kr else 0.0
            rng    = risk["rng"]
            t = self.time + rng.expovariate(lam_h)
            while t < D:
                if lam_r > 0:
                    back = t + rng.expovariate(lam_r)
                    res  = back if back < D else None
                else:
                    res = None
                engine.add_event(HibernationEvent(t, vm, self.scheduler,
                                                  resume_time=res))
                if res is None:
                    break          # never resumes -> no further events
                t = res + rng.expovariate(lam_h)
            return

        rate = (risk["inherit_rate"] if risk["mode"] == "inherit"
                else vm.hibernation_rate)
        if rate <= 0:
            return

        u  = risk["rng"].random()
        dt = -math.log(1.0 - u) / rate
        t_hib = self.time + dt
        if t_hib >= risk["deadline"]:
            return   # survives to the end of the run

        from simulation.events import HibernationEvent
        engine = self.scheduler.event_engine
        if engine is not None:
            engine.add_event(HibernationEvent(t_hib, vm, self.scheduler))
