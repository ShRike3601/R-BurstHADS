"""
Full comparison sweep: HADS vs Burst-HADS vs R-BurstHADS
=========================================================

REDESIGNED 2026-09-13. The 28 Aug version answered a narrower question
than the post-fix checkpoints already did -- 30 seeds at the single
deadline factor DF=1.0 -- and it could not be run safely: it required a
`run --scenario --ns` subcommand the documented command never passed, and
`run` resumed from results_dynamic_comparison_raw.jsonl, which holds rows
produced before fixes 1-9 that it would have silently counted as done.

What changed, and why:

  * DF span (DFS). A single DF point is not trustworthy on its own. HADS
    and Burst-HADS escalate only when D is threatened, so their makespan
    lands near D and every makespan percentage is partly a statement about
    how much slack D granted. Results are reported across the span.

  * All five Table 9 scenarios of Teylo et al. by default, including sc3
    (kh=1, kr=5), which no earlier grid tested. The thesis's own hand-built
    scenarios remain available but are opt-in (--scenarios): pool
    saturation in particular appears in neither source paper.

  * DF=0.25, below the old tightest point. D is floored at
    main.min_feasible_deadline(), so small-n cells stop tightening once the
    floor binds; every row records `floored` so those cells are not
    mistaken for independent points. Measured before choosing this grid
    (probe, 5 seeds, after fix 8): with an unlimited on-demand pool, HADS
    misses no deadline at any n in {20..300} down to DF=0.25, and
    Burst-HADS / R-BurstHADS miss 0.2-0.6 tasks per run in a handful of
    cells. Deadline pressure in this model shows up as cost, not as
    misses. That is a property of the model, reported rather than tuned
    away.

  * Task counts 50-300. Teylo et al.'s jobs are 60-200 tasks; n=10/20 are
    floor-bound at every DF up to 0.75 and dominated by one or two tasks.

  * Results files are keyed by a fingerprint of the simulator source
    (main.py, models/, scheduler/, simulation/, policies/, metrics/). Any
    code change starts a new sweep_raw_<fingerprint>.jsonl, so `run` can
    only ever resume rows produced by the code on disk, and `summarize`
    reads exactly one code version. Older files are listed, never read.

  * Rows are appended as each unit finishes, so an interrupted run loses
    only units in flight.

Commands (from the project root):
  python experiments\\dynamic_comparison.py              # plan: prints what would run
  python experiments\\dynamic_comparison.py run          # whole default grid, resumable
  python experiments\\dynamic_comparison.py run --scenarios sc1,sc3 --ns 300 --dfs 0.5,1.0 --seeds 0-9
  python experiments\\dynamic_comparison.py summarize    # current code version
  python experiments\\dynamic_comparison.py summarize --fp <fingerprint>
"""

import sys, io, json, math, time, random, hashlib, argparse, contextlib
from pathlib import Path
from multiprocessing import Pool, cpu_count

HERE         = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Teylo et al. Table 9: per-VM Poisson, lambda_h = kh/D, lambda_r = kr/D.
TABLE9 = {
    "sc1": dict(kh=1.0, kr=0.0),
    "sc2": dict(kh=5.0, kr=0.0),
    "sc3": dict(kh=1.0, kr=5.0),
    "sc4": dict(kh=5.0, kr=5.0),
    "sc5": dict(kh=3.0, kr=2.5),
}
SUPPLEMENTARY = ["none", "saturated_early", "saturated_late",
                 "poisson_natural", "single_hib"]
ALL_SCENARIOS = list(TABLE9) + SUPPLEMENTARY

DEFAULT_SCENARIOS = list(TABLE9)
TASK_COUNTS       = [50, 100, 200, 300]
DFS               = [0.25, 0.5, 1.0, 2.0]
RUNS_PER_CONFIG   = 30
SPOT_RISK_MODE    = "declared"   # governs only the supplementary scenarios

SCHEDULER_KEYS   = ["hads", "burst", "rburst"]
SCHEDULER_LABELS = {"hads": "HADS", "burst": "BurstHADS",
                    "rburst": "R-BurstHADS"}

# Supplementary-scenario parameters, unchanged from the 28 Aug version.
HIB_OFFSET = 90.0
HIB_GAP    = 15.0
KH_M5      = 5.0
_HIB_TARGET = {
    "none":            "all_spot",      # unused (no events injected)
    "saturated_early": "all_spot",
    "saturated_late":  "all_spot",
    "poisson_natural": "all_spot",
    "single_hib":      "highest_risk",
}

SIM_SOURCES = ["main.py", "models", "scheduler", "simulation", "policies",
               "metrics"]


# ── CODE VERSIONING ──────────────────────────────────────────────────────────

def code_fingerprint():
    """First 12 hex chars of a SHA-256 over every simulator source file,
    path and content, with line endings normalised so a git autocrlf
    checkout does not look like a code change."""
    h = hashlib.sha256()
    files = []
    for entry in SIM_SOURCES:
        p = PROJECT_ROOT / entry
        files.extend([p] if p.is_file() else sorted(p.glob("*.py")))
    for f in files:
        h.update(f.relative_to(PROJECT_ROOT).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def raw_path(fp):
    return HERE / f"sweep_raw_{fp}.jsonl"


def summary_path(fp):
    return HERE / f"sweep_summary_{fp}.json"


# ── ONE SIMULATION ───────────────────────────────────────────────────────────

def _hib_time_for(scenario, n, seed, deadline):
    """Scripted hibernation times for the supplementary scenarios. Table 9
    scenarios return None: their events come from kh/kr inside
    run_simulation."""
    if scenario in TABLE9 or scenario == "none":
        return None
    import numpy as np
    from main import get_expected_makespan

    expected_mk = get_expected_makespan(n)
    np_rng      = np.random.default_rng(seed + 10000)

    if scenario == "saturated_early":
        return [HIB_OFFSET, HIB_OFFSET + HIB_GAP]
    if scenario == "saturated_late":
        late = max(HIB_OFFSET, expected_mk * 0.40)
        return [late, late + HIB_GAP]
    if scenario == "poisson_natural":
        lam_m5 = KH_M5 / deadline
        lam_c5 = 0.03 / 3600.0
        evts = []
        t = float(np_rng.exponential(1.0 / lam_m5))
        while t < deadline:
            evts.append(t)
            t += float(np_rng.exponential(1.0 / lam_m5))
        t = float(np_rng.exponential(1.0 / lam_c5))
        while t < deadline:
            evts.append(t)
            t += float(np_rng.exponential(1.0 / lam_c5))
        return sorted(evts)[:6] if evts else None
    if scenario == "single_hib":
        return [HIB_OFFSET]
    return None


def run_one_unit(args):
    """One (scenario, n, df, seed, scheduler) -> one row."""
    scenario, n, df, seed, key, fp = args
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from main import (run_simulation, generate_tasks, compute_deadlines,
                      build_vms_dburst, min_feasible_deadline,
                      ideal_makespan, DEADLINE_SLACK)
    from models.vm import VM
    from scheduler.hads         import HADS
    from scheduler.burst_hads   import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS

    base_cls = {"hads": HADS, "burst": BurstHADS, "rburst": RBurstHADS}[key]
    holder = {}

    class _Capture(base_cls):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            holder["s"] = self

    D, _ = compute_deadlines(n, df, 1)
    row = {"fp": fp, "scenario": scenario, "n": n, "df": df, "seed": seed,
           "key": key, "D": D,
           "floored": df * DEADLINE_SLACK * ideal_makespan(n)
                      < min_feasible_deadline(),
           "infeasible": False, "error": None}
    try:
        from models.limits import NoFeasibleSchedule
    except ImportError:                    # code before instance limits
        class NoFeasibleSchedule(Exception):
            pass
    try:
        hib_time = _hib_time_for(scenario, n, seed, D)

        # Re-seed right before generating tasks so every scheduler for
        # this (scenario, n, df, seed) sees an identical task set.
        random.seed(seed)
        tasks = generate_tasks(n)

        kwargs = dict(vm_builder=build_vms_dburst, spot_risk_seed=seed,
                      spot_risk_mode=SPOT_RISK_MODE)
        if scenario in TABLE9:
            kwargs.update(TABLE9[scenario])
        else:
            kwargs.update(hibernation_time=hib_time,
                          hibernate_target=_HIB_TARGET[scenario])
        with contextlib.redirect_stdout(io.StringIO()):
            m = run_simulation(_Capture, tasks, D, **kwargs)

        mk    = m.makespan()
        all_t = [t for job in m.jobs for st in job.stages for t in st.tasks]
        billed = {VM.SPOT: 0, VM.BURSTABLE: 0, VM.ONDEMAND: 0}
        for vm in m.vms:
            if vm._billing_intervals:
                billed[vm.market] += 1
        row.update(
            mk=mk, mk_frac=mk / D, cost=m.total_cost(),
            misses=m.deadline_misses(),
            pct=100.0 * sum(t.completed for t in all_t) / len(all_t),
            n_provisioned=len(getattr(holder.get("s"), "provisioned_vms",
                                      None) or []),
            vms_billed=billed,
        )
        launches = getattr(holder.get("s"), "_launches", None)
        if launches is not None:
            row.update(launched=launches.launched(),
                       limit_overrides=launches.overrides)
    except NoFeasibleSchedule as e:
        # The primary schedule cannot meet D within the instance limits.
        # The reference raises here too; this is a result, not a crash.
        row.update(infeasible=True, infeasible_reason=str(e))
    except Exception as e:
        row["error"] = repr(e)
    return row


# ── GRID / STORAGE ───────────────────────────────────────────────────────────

def _load_rows(path):
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _unit_key(r):
    return (r["scenario"], r["n"], r["df"], r["seed"], r["key"])


def _parse_list(spec, cast, default):
    return [cast(x) for x in spec.split(",")] if spec else list(default)


def _parse_seeds(spec):
    if not spec:
        return list(range(RUNS_PER_CONFIG))
    lo, hi = spec.split("-")
    return list(range(int(lo), int(hi) + 1))


def _grid(args):
    scenarios = _parse_list(getattr(args, "scenarios", None), str,
                            DEFAULT_SCENARIOS)
    bad = [s for s in scenarios if s not in ALL_SCENARIOS]
    if bad:
        raise SystemExit(f"unknown scenario(s) {bad}; have {ALL_SCENARIOS}")
    ns    = _parse_list(getattr(args, "ns", None), int, TASK_COUNTS)
    dfs   = _parse_list(getattr(args, "dfs", None), float, DFS)
    seeds = _parse_seeds(getattr(args, "seeds", None))
    return scenarios, ns, dfs, seeds


def _pending(args, fp):
    scenarios, ns, dfs, seeds = _grid(args)
    units = [(sc, n, df, s, k, fp) for sc in scenarios for n in ns
             for df in dfs for s in seeds for k in SCHEDULER_KEYS]
    done = {_unit_key(r) for r in _load_rows(raw_path(fp))
            if r["error"] is None}
    todo = [u for u in units if u[:5] not in done]
    return (scenarios, ns, dfs, seeds), units, todo


# ── COMMANDS ─────────────────────────────────────────────────────────────────

def cmd_plan(args):
    fp = code_fingerprint()
    (scenarios, ns, dfs, seeds), units, todo = _pending(args, fp)
    path = raw_path(fp)
    print(f"code fingerprint : {fp}")
    print(f"results file     : {path.name} "
          f"({'exists' if path.exists() else 'new'})")
    print(f"grid             : scenarios={scenarios} ns={ns} dfs={dfs} "
          f"seeds={seeds[0]}-{seeds[-1]} schedulers={SCHEDULER_KEYS}")
    print(f"units            : {len(units)} total, "
          f"{len(units) - len(todo)} done, {len(todo)} to run")
    others = [p.name for p in sorted(HERE.glob("sweep_raw_*.jsonl"))
              if p != path]
    if others:
        print(f"other code versions (never read): {others}")
    print("\nnothing was run. to run this grid: "
          "python experiments\\dynamic_comparison.py run [same options]")


def cmd_run(args):
    fp = code_fingerprint()
    _, units, todo = _pending(args, fp)
    path = raw_path(fp)
    if not todo:
        print(f"nothing to do: all {len(units)} units present in {path.name}")
        return
    print(f"running {len(todo)} of {len(units)} units on {args.workers} "
          f"workers -> {path.name}", flush=True)
    t0, errors = time.time(), 0
    with Pool(args.workers) as pool, open(path, "a") as f:
        for i, r in enumerate(pool.imap_unordered(run_one_unit, todo,
                                                  chunksize=2)):
            f.write(json.dumps(r) + "\n")
            f.flush()
            errors += r["error"] is not None
            if (i + 1) % 500 == 0 or i + 1 == len(todo):
                print(f"  {i+1}/{len(todo)}  {time.time() - t0:.0f}s  "
                      f"errors={errors}", flush=True)
    if errors:
        print(f"{errors} units raised; they are recorded with their error "
              f"and will be retried by the next `run`.")


def _stats(xs):
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) \
        if len(xs) > 1 else 0.0
    return m, sd


def cmd_summarize(args):
    fp = args.fp or code_fingerprint()
    path = raw_path(fp)
    if not path.exists():
        raise SystemExit(f"no results for code fingerprint {fp} ({path.name})")

    latest = {}
    for r in _load_rows(path):
        latest[_unit_key(r)] = r          # a retried unit's last row wins

    cells = {}
    for r in latest.values():
        cells.setdefault((r["scenario"], r["n"], r["df"]), []).append(r)

    out = []
    for (sc, n, df) in sorted(cells, key=lambda c: (ALL_SCENARIOS.index(c[0]),
                                                     c[1], c[2])):
        rows = cells[(sc, n, df)]
        cell = {"scenario": sc, "n": n, "df": df, "D": rows[0]["D"],
                "floored": rows[0]["floored"]}
        for k in SCHEDULER_KEYS:
            ok  = [r for r in rows if r["key"] == k and r["error"] is None
                   and not r.get("infeasible")]
            inf = [r for r in rows if r["key"] == k and r.get("infeasible")]
            err = [r for r in rows if r["key"] == k and r["error"] is not None]
            st = {"runs": len(ok), "infeasible": len(inf), "errors": len(err)}
            for field in ("mk", "cost", "misses", "pct", "mk_frac",
                          "n_provisioned"):
                st[f"{field}_mean"], st[f"{field}_std"] = _stats(
                    [r[field] for r in ok])
            cell[k] = st
        h = cell["hads"]
        for k in ("burst", "rburst"):
            if h["mk_mean"] and cell[k]["mk_mean"] is not None:
                cell[k]["mk_vs_hads_pct"] = (100.0 * (cell[k]["mk_mean"]
                                             - h["mk_mean"]) / h["mk_mean"])
                cell[k]["cost_vs_hads_pct"] = (100.0 * (cell[k]["cost_mean"]
                                               - h["cost_mean"]) / h["cost_mean"])
        b, r_ = cell["burst"], cell["rburst"]
        cell["rburst_dominates_burst"] = (
            None if b["mk_mean"] is None or r_["mk_mean"] is None
            else r_["mk_mean"] <= b["mk_mean"]
            and r_["cost_mean"] <= b["cost_mean"])
        out.append(cell)

    json.dump({"fp": fp, "cells": out}, open(summary_path(fp), "w"), indent=1)

    print(f"code fingerprint {fp}: {len(latest)} units in {len(out)} cells")
    print(f"{'cell':24s} {'DF':>5s} | {'HADS mk':>8s} {'$':>7s} {'miss':>5s} | "
          f"{'Burst mk%':>9s} {'$%':>6s} {'miss':>5s} | "
          f"{'R mk%':>6s} {'$%':>6s} {'miss':>5s} | dom runs")
    short = []
    for c in out:
        h, b, r_ = c["hads"], c["burst"], c["rburst"]
        runs = min(h["runs"], b["runs"], r_["runs"])
        if runs < RUNS_PER_CONFIG:
            short.append((c["scenario"], c["n"], c["df"], runs))
        label = (f"{c['scenario']} n={c['n']}"
                 + ("*" if c["floored"] else ""))
        if h["mk_mean"] is None or b["mk_mean"] is None or r_["mk_mean"] is None:
            print(f"{label:24s} {c['df']:5.2f} | no feasible runs for some "
                  f"scheduler; infeasible H/B/R "
                  f"{h['infeasible']}/{b['infeasible']}/{r_['infeasible']}")
            continue
        print(f"{label:24s} {c['df']:5.2f} | {h['mk_mean']:8.0f} {h['cost_mean']:7.3f} "
              f"{h['misses_mean']:5.1f} | {b['mk_vs_hads_pct']:+9.1f} "
              f"{b['cost_vs_hads_pct']:+6.1f} {b['misses_mean']:5.1f} | "
              f"{r_['mk_vs_hads_pct']:+6.1f} {r_['cost_vs_hads_pct']:+6.1f} "
              f"{r_['misses_mean']:5.1f} |  {'Y' if c['rburst_dominates_burst'] else 'N'}  {runs}")
    print("(* = D set by min_feasible_deadline floor)")
    infeasible = {k: sum(c[k]["infeasible"] for c in out) for k in SCHEDULER_KEYS}
    print(f"infeasible runs (no primary schedule within D and the instance "
          f"limits): {infeasible}")
    if short:
        print(f"[WARNING] {len(short)} cells below {RUNS_PER_CONFIG} seeds: "
              f"{short[:10]}{' ...' if len(short) > 10 else ''}")
    errs = sum(c[k]["errors"] for c in out for k in SCHEDULER_KEYS)
    if errs:
        print(f"[WARNING] {errs} units ended in an error; see {path.name}")
    print(f"wrote {summary_path(fp).name}")


def _add_grid_args(p):
    p.add_argument("--scenarios", help=f"comma list; default "
                   f"{','.join(DEFAULT_SCENARIOS)}; also {','.join(SUPPLEMENTARY)}")
    p.add_argument("--ns", help=f"comma list; default "
                   f"{','.join(map(str, TASK_COUNTS))}")
    p.add_argument("--dfs", help=f"comma list; default "
                   f"{','.join(map(str, DFS))}")
    p.add_argument("--seeds", help=f"inclusive range lo-hi; default "
                   f"0-{RUNS_PER_CONFIG - 1}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HADS / Burst-HADS / R-BurstHADS sweep. "
                    "No subcommand = plan (runs nothing).")
    sub = parser.add_subparsers(dest="cmd")
    _add_grid_args(sub.add_parser("plan", help="print what `run` would do"))
    p_run = sub.add_parser("run", help="run the grid, resuming this code "
                                       "version's results file")
    _add_grid_args(p_run)
    p_run.add_argument("--workers", type=int, default=max(1, cpu_count()))
    p_sum = sub.add_parser("summarize", help="aggregate one code version")
    p_sum.add_argument("--fp", help="code fingerprint; default: current code")

    args = parser.parse_args()
    {"plan": cmd_plan, "run": cmd_run, "summarize": cmd_summarize,
     None: cmd_plan}[args.cmd](args)
