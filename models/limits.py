"""
Account-level instance limits, taken from the reference implementation.

CCScheduler (HADS) and IPDPS (Burst-HADS) in github.com/luanteylo/hads_
never launch more instances of a type than its configured limit,
restrictions.limits.{on-demand, preemptible}, and IPDPS also checks
global_limits.ec2.{on-demand, preemptible}. Both configurations shipped
with the reference, input/example/env.json and input/masa/env.json, set
every instance type to 5 on-demand and 5 preemptible, within global
limits of 20 and 20. A burstable instance is launched on the on-demand
market, and IPDPS's burstable allocation checks it against that type's
on-demand limit.

What the reference does at a limit:
  primary schedule  skips the type; if no type can take the task it
                    raises "THERE IS NO SOLUTION WITH THAT DEADLINE"
                    (NoFeasibleSchedule here)
  migration         CCScheduler.backup_heuristic tries a new on-demand VM
                    within the deadline and the limit, then any new
                    on-demand VM within the limit; if the limit is spent
                    the task is left unallocated

Counts are of instances LAUNCHED during the job and are never decremented
when one terminates, as count_dict / count_list are in the reference.

ENABLED = False reproduces the uncapped simulator of fixes 1-10.
"""

ENABLED = False

# Keyed by models.vm.VM market values. Burstable VMs count as on-demand.
PER_TYPE = {"ondemand": 5, "spot": 5}
GLOBAL   = {"ondemand": 20, "spot": 20}

# Markets the limits apply to. The reference limits both.
MARKETS  = ("ondemand", "spot")


class NoFeasibleSchedule(RuntimeError):
    """The primary scheduler found no placement within the deadline and
    the instance limits. The reference raises here too. It is an outcome
    to report (an infeasible run), not a crash to retry."""


def _market_key(vm):
    """Burstable VMs are launched on the on-demand market."""
    return "spot" if vm.market == "spot" else "ondemand"


class LaunchCounter:
    """Instances one scheduler has launched during a job, by market and
    type. Never decremented, as in the reference. A VM counts once, the
    first time it is committed: when the primary schedule uses it, when a
    scheduler creates it, or when a migration first places work on a pool
    VM that had not been launched."""

    def __init__(self):
        self._ids = {}            # vm.id -> (market key, vm_type)
        self.overrides = 0        # launches forced past a spent limit

    def _room(self, key, vm_type):
        if not ENABLED or key not in MARKETS:
            return True
        per_type = sum(1 for k, t in self._ids.values()
                       if k == key and t == vm_type)
        total = sum(1 for k, _ in self._ids.values() if k == key)
        return per_type < PER_TYPE[key] and total < GLOBAL[key]

    def can_launch(self, vm):
        return vm.id in self._ids or self._room(_market_key(vm), vm.vm_type)

    def can_launch_type(self, key, vm_type):
        return self._room(key, vm_type)

    def commit(self, vm):
        self._ids.setdefault(vm.id, (_market_key(vm), vm.vm_type))

    def launched(self):
        out = {}
        for k, t in self._ids.values():
            out[f"{k}:{t}"] = out.get(f"{k}:{t}", 0) + 1
        return out
