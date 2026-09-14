"""
Fixed launch catalogues, captured once when a scheduler starts.

A scheduler's pool lists (ondemand_vms, burstable_vms) are LIVE: terminated
VMs are removed from them. Reading a launch template from those lists could
find them empty mid-run, which is how launches used to fall back to a
hardcoded c5.large at speed 2 and $0.085 in every catalogue (DEVIATIONS E3).
"""
from models.vm import VM


def _template(v):
    return dict(vm_type=v.vm_type, market=v.market, speed=v.speed,
                cost_rate=v.cost_rate, memory_gb=v.memory_gb,
                vcpu=v.vcpu_count, baseline_fraction=v.baseline_fraction)


def catalogue(vms, market):
    """One template per instance type of `market` in `vms`, cheapest first
    (ties by type name). Algorithm 4 Attempt 3 and CCScheduler's
    backup_heuristic both walk M^o sorted by price."""
    seen = {}
    for v in vms:
        if v.market == market and v.vm_type not in seen:
            seen[v.vm_type] = _template(v)
    return sorted(seen.values(), key=lambda t: (t["cost_rate"], t["vm_type"]))


def make_vm(tpl, vm_id):
    kw = dict(vm_id=vm_id, vm_type=tpl["vm_type"], market=tpl["market"],
              speed=tpl["speed"], cost_rate=tpl["cost_rate"],
              memory_gb=tpl["memory_gb"], hibernation_rate=0.0,
              vcpu_count=tpl["vcpu"])
    if tpl["market"] == VM.BURSTABLE:
        kw["baseline_fraction"] = tpl["baseline_fraction"]
    return VM(**kw)
