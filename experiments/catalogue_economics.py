"""
Price per unit of work for every VM in our two catalogues and in TCC23's
Table 3. Numbers are read from the code's own builders, not retyped.

  units/h     = per-core speed x usable slots. Usable slots is vcpu_count AS
                THE VM MODEL HOLDS IT: models.vm.VM forces every burstable to
                one slot (TCC23 sections 3.2 and 3.4: one task per burstable
                VM), whatever its real vCPU count.
  $/unit      = price per hour / units per hour, the machine fully used.
  $/unit, one task
              = price / speed: what one task pays for a VM it has alone.
  baseline    = burstable in baseline mode (speed x baseline_fraction).

Usage: python experiments\\catalogue_economics.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))


def rows_from(vms):
    seen, out = set(), []
    for v in vms:
        key = (v.vm_type, v.market)
        if key in seen:
            continue
        seen.add(key)
        rate = v.cost_rate * 3600
        units = v.speed * v.vcpu_count
        out.append(dict(type=v.vm_type, market=v.market, speed=v.speed, slots=v.vcpu_count,
                        rate=rate, per_unit=rate / units, one_task=rate / v.speed,
                        baseline=(rate / (v.speed * v.baseline_fraction)) if v.is_burstable else None))
    return out


def show(title, rows):
    print(title)
    print(f"  {'type':10s} {'market':9s} {'speed':>5s} {'slots':>5s} {'units':>5s} {'$/h':>7s}"
          f" {'$/unit':>8s} {'$/unit 1 task':>13s} {'$/unit baseline':>15s}")
    for r in sorted(rows, key=lambda r: r["per_unit"]):
        b = f"{r['baseline']:15.4f}" if r["baseline"] is not None else f"{'':15s}"
        print(f"  {r['type']:10s} {r['market']:9s} {r['speed']:5.2f} {r['slots']:5d} {r['speed'] * r['slots']:5.2f}"
              f" {r['rate']:7.4f} {r['per_unit']:8.5f} {r['one_task']:13.5f} {b}")
    print()


def main():
    import main as m
    from experiments import paper_reproduction as pr
    import tcc23_tables as tt
    from models.vm import VM

    show("SWEEP CATALOGUE (main.build_vms_dburst, used by the main sweep)", rows_from(m.build_vms_dburst()))
    show("VALIDATION CATALOGUE (paper_reproduction.build_vms_paper, used by Round A)",
         rows_from(pr.build_vms_paper(1)))

    # TCC23 Table 3: prices and vCPUs only. Equal per-core speed assumed (the
    # paper publishes none); burstables one slot, per the paper's own rule.
    rows = []
    for t, (vcpu, mem, od, spot, base) in tt.T3.items():
        for market, price in (("ondemand", od), ("spot", spot)):
            if price is None:
                continue
            is_b = base is not None
            slots = 1 if is_b else vcpu
            rows.append(dict(type=t, market="burstable" if is_b else market, speed=1.0, slots=slots,
                             rate=price, per_unit=price / slots, one_task=price,
                             baseline=(price / base) if is_b else None))
    show("TCC23 TABLE 3 (equal per-core speed assumed; burstable one slot)", rows)

    print("BURSTABLE vs CHEAPEST REGULAR ON-DEMAND, $ per unit of work")
    for name, vms in (("sweep", m.build_vms_dburst()), ("validation", pr.build_vms_paper(1))):
        r = rows_from(vms)
        b = next(x for x in r if x["market"] == VM.BURSTABLE)
        od = min((x for x in r if x["market"] == VM.ONDEMAND), key=lambda x: x["per_unit"])
        print(f"  {name:10s} burst mode {b['per_unit']:.5f} vs {od['type']} on-demand {od['per_unit']:.5f}"
              f" per core -> x{b['per_unit'] / od['per_unit']:.2f}; vs one task alone on it"
              f" {od['one_task']:.5f} -> x{b['per_unit'] / od['one_task']:.2f}")
    tb = tt.T3["t3.large"]
    cheapest_od = min(tt.T3[t][2] / tt.T3[t][0] for t in tt.T3 if tt.T3[t][4] is None)
    print(f"  TCC23      burst mode {tb[2]:.5f} vs cheapest on-demand per core {cheapest_od:.5f}"
          f" -> x{tb[2] / cheapest_od:.2f}  (per vCPU, ignoring the one-task rule: {tb[2] / tb[0]:.5f}"
          f" -> x{tb[2] / tb[0] / cheapest_od:.2f})")

    print("\nCOUNTERFACTUAL t3.large per-core speed in the sweep catalogue (price fixed, one slot)")
    rate = next(x for x in rows_from(m.build_vms_dburst()) if x["market"] == VM.BURSTABLE)["rate"]
    od = min((x for x in rows_from(m.build_vms_dburst()) if x["market"] == VM.ONDEMAND), key=lambda x: x["per_unit"])
    for sp in (1.7, 2.0):
        for slots in (1, 2):
            print(f"  speed {sp} x {slots} slot(s): {rate / (sp * slots):.5f} $/unit"
                  f" -> x{rate / (sp * slots) / od['per_unit']:.2f} of {od['type']} on-demand")


if __name__ == "__main__":
    main()
