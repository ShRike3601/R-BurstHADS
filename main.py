"""
Main simulation entry point — P-BurstHADS experiments.

VM POOL DESIGN (matches paper scale, modern instance types):
  5 VMs total, matching Teylo et al. (2023) pool size.

  HADS pool (3 VMs):
    spot:     c5.large  (low-risk anchor, illustrative)
              m5.xlarge (high-risk anchor, illustrative)
    ondemand: c5.large

  BurstHADS / P-BurstHADS pool (5 VMs):
    spot:     c5.large  (low-risk anchor, illustrative)
              c5.xlarge (low-risk anchor, illustrative)
              m5.xlarge (high-risk anchor, illustrative)
    burstable: t3.large (no risk,   0/hr)
    ondemand:  c5.large (no risk,   0/hr)

HIBERNATION RATE CALIBRATION -- read this before citing these numbers:
  These hibernation_rate values are NOT derived from AWS Spot Advisor
  data (an earlier version of this file claimed they were -- checked
  against AWS's actual published interruption-frequency tables, that
  claim does not hold; the numbers were off by 4-5 orders of
  magnitude). They instead follow Teylo et al. (2023)'s own
  methodology: the paper is explicit that its hibernation/resume
  events are SYNTHETIC and Poisson-distributed (lambda = k/D, where k
  is the expected event count over the deadline D), not measured from
  AWS. Their Table 9 worst case (sc2) uses k=5 over D=2700s, i.e.
  about 6.7 events/hr.

  m5.xlarge's hibernation_rate below (5/2700 per second) matches
  Teylo's sc2 exactly. c5.large/c5.xlarge's rate (0.03-0.04/hr) has no
  equivalent in Teylo's paper -- the paper does not differentiate
  hibernation risk by instance type at all. That differentiation is
  this thesis's OWN assumption. The gap between m5.xlarge and c5.large
  is a deliberately large, illustrative contrast -- not a claim about
  real-world AWS interruption-frequency differences between these types.

WHERE THE DECLARED RATES ARE USED (verified 2026-09-14):
  - Table 9 scenarios (run_simulation with kh set) do NOT use them.
    Every spot VM of every type, in the pool or provisioned mid-run, is
    hibernated at lambda_h = kh/D and resumed at lambda_r = kr/D, so in
    sc1-sc5 c5.large, c5.xlarge and m5.xlarge face the SAME rate.
  - No scheduler's WRR weight reads them. Equation 8's weight
    (BurstHADS.wrr_weight, inherited by R-BurstHADS, and HADS.wrr_weight)
    is speed * vcpu_count / cost_rate, with no risk term. An earlier
    version of this docstring said R-BurstHADS "detects this via
    risk-adjusted WRR weights and assigns long tasks preferentially to
    c5/c5.xlarge over m5.xlarge"; no such mechanism exists in the code.
  - R-BurstHADS reads them in exactly two places. Theorem 1
    (_preemptive_provision) fires only for m5.xlarge, whose declared rate
    gives P(hibernation) ~0.22 over one average task against ~0.001 for
    the c5 types, so the three replacements it buys exist because of this
    illustrative number. The template survival filter
    (_resolve_spot_template) excludes m5.xlarge but never changes the
    choice in this catalogue: c5.xlarge leads on capacity per dollar
    (130.7 against m5.xlarge's 97.1) with or without it.
  So in every Table 9 cell R-BurstHADS reasons about a risk differential
  the experiment does not instantiate. Its risk-awareness is untested
  there and must not be claimed as a source of any reported benefit.

HIBERNATION INJECTION (supplementary hand-built scenarios only):
  Outside Table 9, run_simulation can hibernate the VM labelled
  highest-risk at a controlled time (hibernate_target="highest_risk") or
  every spot VM (all_spot). That targeting is our extension, not Teylo
  et al.'s -- their Poisson model does not single out an instance type.
"""

import random
import copy
from models.task  import Task
from models.job   import Job
from models.stage import Stage
from models.vm    import VM
from models.utils import flatten_and_assign_deadlines

from simulation.event_engine     import EventEngine
from simulation.execution_engine import start_execution
from simulation.events           import HibernationEvent, TerminationEvent
from metrics.metrics             import Metrics


# ── PER-CORE PERFORMANCE ─────────────────────────────────────────────────────
# `speed` is workload units retired per second BY ONE CORE. A VM runs
# vcpu_count tasks concurrently and each of them runs at `speed`, so
# whole-machine capacity is speed * vcpu_count -- which is how
# spot_pool_throughput(), Equation 8's WRR weight and every finish-time
# estimator use it.
#
# CORRECTION (2026-09-13). These values used to scale with instance
# SIZE: c5.large speed 2 on 2 vCPU, c5.xlarge speed 4 on 4 vCPU. That
# counted size twice, once in `speed` and again in `vcpu_count`, so the
# model believed a c5.xlarge retired FOUR times a c5.large's work for
# twice the money. On AWS the two are the same processor generation at
# the same clock and a c5.xlarge is simply two c5.larges at exactly
# twice the price, so their price/performance is identical and their
# per-core speed must be identical too.
#
# Two things followed from the old values. Throughput-per-dollar read
# c5.large 131, c5.xlarge 261, m5.xlarge 229, and that is the quantity
# RBurstHADS._resolve_spot_template sorts on -- so its 2x preference for
# c5.xlarge was an artefact of the double count rather than a property of
# the instance. And spot_pool_throughput() read 108 units/s against a
# true 56.4, making every deadline derived from it roughly 1.8x tighter
# than the calibration intended. The DF sweep spans that shift, so no
# recalibration of DEADLINE_SLACK is required: DF and DEADLINE_SLACK only
# ever appear as a product.
#
# The values themselves: the c5 family is compute-optimised (Xeon
# Platinum at a high sustained clock); m5 and t3 are general purpose at a
# lower one. 2.0 against 1.7 per core reflects that ratio and claims
# nothing more. t3.large's entry is its BURST-mode per-core speed;
# baseline mode applies baseline_fraction on top.
PER_CORE_SPEED = {
    "c5.large":  2.0,
    "c5.xlarge": 2.0,
    "m5.xlarge": 1.7,
    "t3.large":  1.7,
}


# ── VM POOLS ──────────────────────────────────────────────────────────────────

def build_vms_burst():
    """
    BurstHADS / P-BurstHADS pool: 5 VMs total.
    m5.xlarge is modeled with a much higher hibernation rate than
    c5.large -- an illustrative contrast, not an AWS-measured
    differential (see module docstring). Legacy pool, not used by the
    sweep; no scheduler's WRR weight reads the hibernation rate.
    """
    return [
        # Spot — low hibernation risk
        VM(0, "c5.large",  VM.SPOT,      speed=2, cost_rate=0.0306/3600,
           memory_gb=4.0,  hibernation_rate=0.03/3600, vcpu_count=2),
        # Spot — low hibernation risk, faster
        VM(1, "c5.xlarge", VM.SPOT,      speed=PER_CORE_SPEED["c5.xlarge"], cost_rate=0.0612/3600,
           memory_gb=8.0,  hibernation_rate=0.04/3600, vcpu_count=4),
        # Spot — HIGH hibernation risk (5.7x higher than c5.large)
        VM(2, "m5.xlarge", VM.SPOT,      speed=PER_CORE_SPEED["m5.xlarge"], cost_rate=0.0700/3600,
           memory_gb=16.0, hibernation_rate=5.0/2700, vcpu_count=4),  # Teylo et al. sc2 (kh=5, D=2700s), illustrative high-risk anchor
        # Second safe fast spot VM — gives P-BurstHADS same speed-4
        # capacity as BurstHADS (which uses m5.xlarge as second speed-4)
        VM(3, "c5.xlarge", VM.SPOT,      speed=PER_CORE_SPEED["c5.xlarge"], cost_rate=0.0612/3600,
           memory_gb=8.0,  hibernation_rate=0.04/3600, vcpu_count=4),
        # Burstable — recovery buffer, zero hibernation risk
        VM(4, "t3.large",  VM.BURSTABLE, speed=PER_CORE_SPEED["t3.large"], cost_rate=0.0832/3600,
           memory_gb=8.0,  baseline_fraction=0.20, hibernation_rate=0.0, vcpu_count=2),
        # On-demand — guaranteed fallback
        VM(5, "c5.large",  VM.ONDEMAND,  speed=2, cost_rate=0.085/3600,
           memory_gb=4.0,  hibernation_rate=0.0, vcpu_count=2),
    ]


def build_vms_hads():
    """
    HADS pool: 3 VMs, spot + on-demand only.
    No burstable — HADS was designed without burstable VMs.
    Same spot types as BurstHADS for fair comparison.
    """
    return [
        VM(0, "c5.large",  VM.SPOT,     speed=2, cost_rate=0.0306/3600,
           memory_gb=4.0,  hibernation_rate=0.03/3600, vcpu_count=2),
        VM(1, "m5.xlarge", VM.SPOT,     speed=PER_CORE_SPEED["m5.xlarge"], cost_rate=0.0700/3600,
           memory_gb=16.0, hibernation_rate=5.0/2700, vcpu_count=4),  # Teylo et al. sc2 (kh=5, D=2700s), illustrative high-risk anchor
        VM(2, "c5.large",  VM.ONDEMAND, speed=2, cost_rate=0.085/3600,
           memory_gb=4.0,  hibernation_rate=0.0, vcpu_count=2),
    ]


SPOT_COPIES = 3   # instances of EACH spot type in the shared pool

def build_vms_dburst():
    """
    Shared base pool used by HADS, BurstHADS, and R-BurstHADS in every
    comparison experiment.

    Includes one burstable VM (t3.large). This is NOT a handicap
    against HADS: Burst-HADS's entire contribution over HADS is
    exploiting burstable instances (paper Section 3.2 / Algorithm 4),
    so a pool that includes one is exercising exactly the capability
    being studied. HADS's real algorithm (ported faithfully from
    CCScheduler.py) has no concept of a burstable market at all --
    scheduler/hads.py never places a task on one, structurally,
    regardless of pool composition. Its presence here doesn't cost
    HADS anything it could have used; it's simply the feature
    BurstHADS/R-BurstHADS are being tested against a baseline that
    predates it.

    D-BurstHADS/R-BurstHADS additionally provisions spot replacements
    reactively on top of this base pool (see scheduler/r_burst_hads.py,
    Theorem 1/2).

    INSTANCE PARITY (2026-08-27). c5.xlarge is included here
    deliberately. R-BurstHADS's reactive provisioning has always
    launched c5.xlarge spot VMs, but this shared pool did not contain
    that type -- it was present in the older build_vms_burst() pool and
    was dropped when this pool was introduced, while r_burst_hads.py's
    hardcoded SPOT_* constants were not updated to match. The effect was
    that R-BurstHADS could obtain an instance type neither baseline's
    planner could ever select, at 261 units/$ against c5.large spot's
    131 -- so the measured advantage was partly an artefact of catalogue
    access rather than of scheduling policy. Restoring c5.xlarge to the
    shared pool means all three schedulers draw from one catalogue, and
    R-BurstHADS now provisions FROM this pool rather than from private
    constants (see RBurstHADS._resolve_spot_template).

    POOL SIZE (2026-08-27). SPOT_COPIES instances of each spot type
    rather than one. Not cosmetic -- it is what makes the comparison
    capable of showing a difference at all.

    HADS's greedy packs to Dspot and stops, so it uses only as many VMs
    as the deadline forces. Burst-HADS's ILS minimises
    alpha*cost + (1-alpha)*makespan with alpha=0.5, so it SPREADS to buy
    makespan. That difference is the entire mechanism behind Teylo et
    al.'s reported 11-44% makespan reduction -- and it can only appear if
    there are spare instances left for the ILS to spread onto. With a
    single instance of each type both schedulers are capacity-bound, both
    land on the same placement, and the reported gap collapses to noise:
    measured at n=50, Burst-HADS came out 0.1% SLOWER than HADS. At three
    copies each, reproducing the paper's own setup, the gap reappeared at
    37-41% against their stated 44.37%/42.09%.

    The deadline scales with the pool automatically -- compute_deadlines
    derives D from spot_pool_throughput() -- so enlarging the pool does
    not slacken the constraint. D stays at DEADLINE_SLACK x the
    perfect-packing bound; there is simply room above the minimum for a
    makespan-optimising scheduler to use.
    """
    vms, vid = [], 0
    spec = [
        # (type,        vcpu, $/hr,   mem_gb, hibernation rate)
        # per-core speed comes from PER_CORE_SPEED -- single-sourced so
        # it cannot drift back into double-counting instance size.
        ("c5.large",    2, 0.0306,  4.0, 0.03/3600),
        ("c5.xlarge",   4, 0.0612,  8.0, 0.04/3600),
        # Teylo et al. sc2 (kh=5, D=2700s) -- illustrative high-risk anchor
        ("m5.xlarge",   4, 0.0700, 16.0, 5.0/2700),
    ]
    for _ in range(SPOT_COPIES):
        for t, vc, rate, mem, hib in spec:
            vms.append(VM(vid, t, VM.SPOT, speed=PER_CORE_SPEED[t],
                          cost_rate=rate/3600,
                          memory_gb=mem, hibernation_rate=hib,
                          vcpu_count=vc))
            vid += 1
    # Burstable template. Burst-HADS launches more elastically from M^b
    # via ceil(burst_rate * |selected_vms|), so one seed instance is enough.
    vms.append(VM(vid, "t3.large", VM.BURSTABLE,
                  speed=PER_CORE_SPEED["t3.large"],
                  cost_rate=0.0832/3600, memory_gb=8.0,
                  baseline_fraction=0.20, hibernation_rate=0.0,
                  vcpu_count=2)); vid += 1
    # On-demand types for the elastic M^o pool, one template each (Algorithm
    # 4 Attempt 3 walks them by price, each within its instance limit, so the
    # on-demand ceiling is min(5 x 3, 20) = 15). The same three non-burstable
    # types as the spot market, as in TCC23 Table 3. AWS us-east-1 Linux
    # on-demand prices (instances.vantage.sh, 2026-09-14); the spot prices
    # above are 36% of these.
    for t, vc, rate, mem in (("c5.large",  2, 0.085, 4.0),
                             ("c5.xlarge", 4, 0.170, 8.0),
                             ("m5.xlarge", 4, 0.192, 16.0)):
        vms.append(VM(vid, t, VM.ONDEMAND, speed=PER_CORE_SPEED[t],
                      cost_rate=rate/3600, memory_gb=mem,
                      hibernation_rate=0.0, vcpu_count=vc))
        vid += 1
    return vms


def build_vms():
    """Alias for backward compatibility."""
    return build_vms_burst()

# Alias for backward compatibility after rename
build_vms_rburst = build_vms_dburst



# ── TASK GENERATION ───────────────────────────────────────────────────────────

def generate_tasks(n_tasks, exec_min=100, exec_max=350):
    """
    Tasks matching paper workload:
      exec_time  : uniform [100, 350] seconds (paper: 102-354s)
      memory_req : uniform [2.85, 13.19] MB   (paper Table 6)
    """
    return [
        Task(i, job_id=0, stage_id=0,
             exec_time=random.randint(exec_min, exec_max),
             memory_req=random.uniform(2.85, 13.19))
        for i in range(n_tasks)
    ]


# ── JOB BUILDERS ─────────────────────────────────────────────────────────────

def build_single_stage_job(tasks, deadline):
    tc = copy.deepcopy(tasks)
    for t in tc:
        t.assigned_vm = None; t.start_time = None
        t.finish_time = None; t.completed = False
        t.current_event = None
        t.exec_start_on_current_vm = None
        t.checkpointed_remaining   = None
        t.remaining_time = t.exec_time
        t.stage_id = 0
    return Job(job_id=0,
               stages=[Stage(stage_id=0, deadline=deadline, tasks=tc)])


def build_multi_stage_job(tasks, stage_deadlines):
    tc = copy.deepcopy(tasks)
    for t in tc:
        t.assigned_vm = None; t.start_time = None
        t.finish_time = None; t.completed = False
        t.current_event = None
        t.exec_start_on_current_vm = None
        t.checkpointed_remaining   = None
        t.remaining_time = t.exec_time

    n_stages        = len(stage_deadlines)
    tasks_per_stage = len(tc) // n_stages
    stages          = []
    for s, dl in enumerate(stage_deadlines):
        start = s * tasks_per_stage
        end   = start + tasks_per_stage if s < n_stages-1 else len(tc)
        for t in tc[start:end]:
            t.stage_id = s
        stages.append(Stage(stage_id=s, deadline=dl,
                            tasks=tc[start:end]))
    return Job(job_id=0, stages=stages)


# ── SIMULATION RUNNER ─────────────────────────────────────────────────────────

def run_simulation(scheduler_class, tasks, deadline,
                   stage_deadlines=None,
                   hibernation_time=None,
                   resume_time=None,
                   termination_time=None,
                   vm_builder=None,
                   hibernate_high_risk=True,
                   hibernate_target=None,
                   spot_risk_seed=None,
                   spot_risk_mode="declared",
                   kh=None, kr=None):
    """
    Run one simulation.

    hibernate_high_risk: if True AND hibernation_time is set,
        hibernates the highest-risk spot VM (m5.xlarge, VM id=1).
        This is the explicit injection approach matching the paper.
        If False, hibernates spot_vms[0] (original behavior).
        Ignored when hibernate_target="most_loaded" is set.

    hibernate_target: overrides hibernate_high_risk entirely when set
        to "most_loaded" -- hibernates whichever spot VM the
        scheduler's own initial placement actually loaded the most
        work onto (by total remaining_time queued), instead of a
        fixed instance type. Use this whenever the comparison
        includes schedulers whose placement logic might avoid a
        fixed target VM. Confirmed need: HADS's WRR weighting always
        prefers the cheaper spot type over the m5.xlarge that
        hibernate_high_risk=True hard-codes as the target, so the old
        default silently never disrupts HADS at all in scenarios with
        only one hibernation event.

    vm_builder: callable returning VM list.
                Auto-selects based on scheduler_class if None.
    """
    from scheduler.hads         import HADS
    from scheduler.r_burst_hads import RBurstHADS

    if vm_builder is None:
        # All schedulers use the same base pool by default
        # D-BurstHADS augments it with preemptive provisioning
        vms = build_vms_dburst()
    else:
        vms = vm_builder()

    if stage_deadlines and len(stage_deadlines) > 1:
        job = build_multi_stage_job(tasks, stage_deadlines)
    else:
        job = build_single_stage_job(tasks, deadline)

    jobs      = [job]
    all_tasks = flatten_and_assign_deadlines(jobs)

    scheduler = scheduler_class(vms, all_tasks, jobs, deadline=deadline)
    scheduler.schedule(0)

    engine = EventEngine(scheduler)
    scheduler.event_engine = engine
    if getattr(scheduler, "_launches", None) is not None:
        # Launches from here on are billed from the engine clock (B1).
        scheduler._launches.now = lambda: engine.time
    start_execution(vms, 0, engine)

    # Start proactive migration checker for P-BurstHADS
    if getattr(scheduler, "proactive_migration", False):
        from simulation.proactive_migration_event import (
            ProactiveMigrationEvent, CHECK_INTERVAL
        )
        engine.add_event(
            ProactiveMigrationEvent(CHECK_INTERVAL, scheduler)
        )

    # ── SPOT RISK FOR VMs PROVISIONED DURING THE RUN ─────────────────
    # Scripted hibernation (below) binds its victims at t=0, so any spot
    # VM created later -- i.e. every replacement R-BurstHADS provisions
    # under Theorem 1/2 -- could never be interrupted. It paid spot
    # prices and carried a declared hibernation_rate while facing zero
    # probability of hibernation, making the replacement fleet immune to
    # the exact failure mode the experiment studies.
    #
    # Fix: every spot VM that becomes ready mid-run is entered into the
    # same Poisson interruption process the paper specifies (lambda_h),
    # drawn from its OWN declared rate. See
    # ProvisioningEvent._expose_to_spot_risk. Deterministic given
    # spot_risk_seed; a dedicated Random instance so it never perturbs
    # the global stream the ILS draws from.
    #
    # spot_risk_mode:
    #   "declared" -- each provisioned VM uses its own hibernation_rate.
    #   "inherit"  -- provisioned VMs inherit the HIGHEST rate among the
    #                 original pool's spot VMs. Use this as a sensitivity
    #                 check: it asks whether the provisioning advantage
    #                 survives when replacements are no safer than what
    #                 they replace, rather than resting on the 167x
    #                 lambda differential between c5.xlarge and
    #                 m5.xlarge, which is this thesis's own illustrative
    #                 choice rather than a measured quantity.
    if spot_risk_seed is not None:
        _orig_spot = [v for v in vms if v.is_spot]
        scheduler._spot_risk = {
            "rng":          random.Random(spot_risk_seed),
            "deadline":     deadline,
            "mode":         spot_risk_mode,
            "inherit_rate": max((v.hibernation_rate for v in _orig_spot),
                                default=0.0),
            # Table 9 rates, so a spot VM launched mid-run joins the same
            # hibernation/resume process as the pool rather than drawing
            # at its declared rate (ProvisioningEvent._expose_to_spot_risk).
            "table9":       (kh, kr) if kh is not None else None,
        }

    # ── TABLE 9 SCENARIOS: per-VM Poisson hibernation, with resume ───
    # Teylo et al. emulate interruptions "using a Poisson distribution
    # function" with rates lambda_h = kh/D and lambda_r = kr/D, as
    # INDIVIDUAL stochastic events per spot VM -- never a pool-wide
    # simultaneous outage. Their Table 9 scenarios are:
    #     sc1 kh=1 kr=0 | sc2 kh=5 kr=0 | sc3 kh=1 kr=5
    #     sc4 kh=5 kr=5 | sc5 kh=3 kr=2.5
    # Three of the five have kr > 0, i.e. hibernation is TEMPORARY and the
    # VM comes back. Our scenarios never passed resume_time at all, so we
    # could only ever express sc1 and sc2, and our own "pool saturation"
    # scenario (every spot VM down at once) is not in the paper -- it is
    # strictly outside the envelope where the burstable rescue mechanism
    # can do anything, since with the whole spot pool gone both schedulers
    # fall through to on-demand and Burst-HADS merely pays extra for idle
    # standby capacity.
    if kh is not None:
        _rng   = random.Random(spot_risk_seed if spot_risk_seed is not None else 0)
        _lam_h = kh / deadline
        _lam_r = (kr / deadline) if kr else 0.0
        for _vm in [v for v in vms if v.is_spot]:
            t = _rng.expovariate(_lam_h)
            while t < deadline:
                if _lam_r > 0:
                    back = t + _rng.expovariate(_lam_r)
                    res  = back if back < deadline else None
                else:
                    back, res = None, None
                engine.add_event(HibernationEvent(t, _vm, scheduler,
                                                  resume_time=res))
                if res is None:
                    break          # never resumes -> no further events
                t = res + _rng.expovariate(_lam_h)

    if hibernation_time is not None:
        spot_vms = [v for v in vms if v.is_spot]
        if spot_vms:
            if hibernate_target == "all_spot":
                # POOL SATURATION, done properly: every spot VM in the
                # pool goes down, staggered by hib_times. Load-independent.
                #
                # Two things this fixes. (1) The scenario is named
                # "pool saturation" but only ever injected TWO events,
                # which was "all of them" in the old two-spot pool and
                # became two-of-three once c5.xlarge was restored for
                # instance parity -- so it silently stopped saturating.
                # (2) It removes the load-dependent targeting below,
                # which was an adversarial oracle: hibernating whichever
                # VM a scheduler had loaded most rewards leaving your
                # fastest machine EMPTY. Measured at n=100: HADS packed
                # all 100 tasks onto c5.xlarge, left m5.xlarge idle, and
                # the rule then spared exactly that idle 16-unit/s VM,
                # which absorbed 76 tasks after the rescue. BurstHADS
                # spread its load, so the rule killed both of its strong
                # VMs and left it the weak c5.large. That is a scheduler
                # being punished for load-balancing, not for handling
                # hibernation badly -- and it inverted the HADS vs
                # BurstHADS ordering the source papers establish.
                #
                # Real spot reclamation is a property of the instance
                # type and the market (lambda_h), never of how deep your
                # queue happens to be.
                order = sorted(spot_vms,
                               key=lambda v: (-v.hibernation_rate, v.id))
                hib_times_all = (hibernation_time
                                 if isinstance(hibernation_time, list)
                                 else [hibernation_time])
                for i, vm in enumerate(order):
                    if i < len(hib_times_all):
                        t_i = hib_times_all[i]
                    else:
                        t_i = hib_times_all[-1] + 15.0 * (i - len(hib_times_all) + 1)
                    res = resume_time if i == len(order) - 1 else None
                    engine.add_event(HibernationEvent(t_i, vm, scheduler,
                                                      resume_time=res))
                spot_vms = []   # fully handled; skip the legacy path below

            elif hibernate_target == "highest_risk":
                # Single interruption, targeted by DECLARED RISK rather
                # than by load -- lambda_h is an instance-type property.
                target = max(spot_vms, key=lambda v: v.hibernation_rate)
            elif hibernate_target == "most_loaded":
                # DEPRECATED -- load-dependent and adversarial; see the
                # "all_spot" note above. Kept only to reproduce earlier runs.
                ranked = sorted(
                    spot_vms,
                    key=lambda v: sum(t.remaining_time for t in v.tasks),
                    reverse=True,
                )
                target = ranked[0]
            elif hibernate_high_risk:
                target = max(spot_vms, key=lambda v: v.memory_gb)  # m5.xlarge: highest memory_gb in every pool
            else:
                target = spot_vms[0]
            # Support list of hibernation times or single time
            hib_times = (hibernation_time
                         if isinstance(hibernation_time, list)
                         else [hibernation_time])
            for i, ht in enumerate(hib_times if spot_vms else []):
                res = resume_time if i == len(hib_times)-1 else None
                engine.add_event(HibernationEvent(
                    ht, target, scheduler, resume_time=res
                ))
            # Second spot VM: hibernate for ALL schedulers symmetrically.
            # Previously gated on isinstance(RBurstHADS) -- now removed.
            others = [v for v in spot_vms if v.id != target.id]
            if others and len(hib_times) > 1:
                if hibernate_target == "most_loaded":
                    second = sorted(
                        others,
                        key=lambda v: sum(t.remaining_time for t in v.tasks),
                        reverse=True,
                    )[0]
                else:
                    second = others[0]
                for ht in hib_times:
                    engine.add_event(HibernationEvent(
                        ht + 15.0, second, scheduler
                    ))

    if termination_time is not None:
        spot_vms = [v for v in vms if v.is_spot]
        if len(spot_vms) > 1:
            target = sorted(spot_vms,
                            key=lambda v: v.memory_gb)[-1]  # m5.xlarge
            engine.add_event(TerminationEvent(
                termination_time, target, scheduler
            ))

    engine.run()
    return Metrics(jobs, vms)


# ── DEADLINE FORMULA ─────────────────────────────────────────────────────────

AVG_RUNTIME = 225.0        # midpoint of the generate_tasks() range [100, 350]

# Empirically calibrated 2026-08-27 against the shared pool (see below).
ACHIEVABLE_FACTOR = 2.0    # a well-behaved scheduler's undisturbed makespan,
                           # as a multiple of the perfect-packing lower bound
DEADLINE_SLACK    = 3.0    # DF=1.0 deadline, as a multiple of that same bound
                           # => DF=1.0 grants ~50% slack over ACHIEVABLE


def spot_pool_throughput(vms=None):
    """
    Task-seconds of work the spot pool retires per wall-clock second.

    Each VM contributes speed * vcpu_count, because a VM runs vcpu_count
    tasks CONCURRENTLY and each of them runs at `speed` (see
    VM.start_next_if_free / VM.estimate_finish_time). Counting only the
    VM count, or only the speed, understates the pool by the other factor.
    """
    if vms is None:
        vms = build_vms_dburst()
    return sum(v.speed * v.vcpu_count for v in vms if v.market == VM.SPOT)


EXEC_MAX            = 350.0   # generate_tasks() upper bound
CHECKPOINT_OVERHEAD = 0.10    # Task.checkpoint_overhead default
FLOOR_MARGIN        = 1.5     # headroom above the infeasibility boundary


def ideal_makespan(n_tasks, vms=None):
    """
    Lower bound on achievable makespan over the spot pool.

    Two binding terms: total work divided by pool throughput, and the
    single longest task on the fastest VM (work cannot be split below one
    task). The second dominates at small n -- at n=10 the work term is
    62.5s but one 350s task on a speed-4 VM already costs 87.5s, so using
    the work term alone would understate the bound by 40% exactly where
    the deadline is tightest.
    """
    if vms is None:
        vms = build_vms_dburst()
    spot = [v for v in vms if v.market == VM.SPOT]
    fastest = max((v.speed for v in spot), default=1.0)
    work_bound = (n_tasks * AVG_RUNTIME) / spot_pool_throughput(vms)
    task_bound = EXEC_MAX / fastest
    return max(work_bound, task_bound)


def min_feasible_deadline(vms=None):
    """
    Floor below which the experiment stops being a scheduling problem.

    BurstHADS and HADS both reserve a migration margin -- BurstHADS'
    compute_dspot() sets Dspot = D - (longest task, inflated by checkpoint
    overhead, on the SLOWEST non-burstable VM) and raises ValueError when
    that is non-positive. So a deadline at or under that margin does not
    produce an interesting "tight deadline" result, it produces an
    exception that the experiment harness then silently drops from the
    sample. Floor D above it so tight cells report deadline MISSES (a
    measurement) instead of vanishing (a bias).
    """
    if vms is None:
        vms = build_vms_dburst()
    nonburst = [v for v in vms if v.market != VM.BURSTABLE]
    slowest = min((v.speed for v in nonburst), default=1.0)
    worst_exec = EXEC_MAX * (1.0 + CHECKPOINT_OVERHEAD) / slowest
    return FLOOR_MARGIN * worst_exec


def compute_deadlines(n_tasks, deadline_factor, n_stages=1, vms=None):
    """
    D = deadline_factor * DEADLINE_SLACK * ideal_makespan(n)

    CALIBRATION NOTE (2026-08-27). The previous formula was

        base = (n_tasks * 225.0) / 3      # "3 spot VMs"

    which divided by a VM COUNT at an implicit speed of 1, ignoring both
    `speed` and `vcpu_count`. The shared pool actually retires 36
    task-units/s, not 3, so that formula produced a deadline 12x the
    perfect-packing bound and the constraint never bound: across all 2700
    runs of the previous sweep, all three schedulers recorded ZERO
    deadline misses and 100% completion in every cell. Worse, both
    baselines only escalate (launch on-demand capacity) when the deadline
    is threatened, so a deadline that can never be threatened meant the
    baselines never escalated -- and the reported gap against
    R-BurstHADS, whose provisioning is NOT deadline-gated, was largely an
    artefact of that.

    Measured undisturbed makespans as a multiple of the bound:
        BurstHADS  n=50 2.36x   n=100 1.53x   n=300 1.16x
        HADS       ~10x at every n (its own placement defect, see notes)
    and under pool saturation BurstHADS runs 6.6-7.6x the bound.

    DEADLINE_SLACK = 3.0 therefore places DF=1.0 where it discriminates:
    a well-packed undisturbed run meets it, a saturated run does not
    unless the scheduler escalates, and DF=0.5 / 2.0 bracket that on
    either side. For scale, this puts D(n=100) at 1875s and D(n=200) at
    3750s, against the fixed D=2700s Teylo et al. use for their 60-200
    task jobs -- the same order of magnitude, where the old formula gave
    7500s and 15000s.
    """
    global_deadline = max(
        deadline_factor * DEADLINE_SLACK * ideal_makespan(n_tasks, vms),
        min_feasible_deadline(vms),
    )
    stage_deadlines = [
        global_deadline * (i+1) / n_stages
        for i in range(n_stages)
    ]
    return global_deadline, stage_deadlines


def get_expected_makespan(n_tasks, vms=None):
    """
    Realistic undisturbed makespan, used to place hibernation events
    (the `saturated_late` scenario injects at 40% of this).

    Previously returned n*22.5, which assumed 3 spot VMs at average speed
    3.33 and again ignored vcpu_count -- overestimating the real run by
    1.5-3x. The consequence was a scenario that did not do what it said:
    at n=300 it placed the "late" hibernation at t=2700s, but BurstHADS
    finishes undisturbed at 2171s, so the event fired after the run was
    already over and `saturated_late` was a silent no-op at that size.
    """
    return ACHIEVABLE_FACTOR * ideal_makespan(n_tasks, vms)


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from scheduler.hads         import HADS
    from scheduler.burst_hads   import BurstHADS
    from scheduler.r_burst_hads import RBurstHADS

    random.seed(42)
    n_tasks = 50
    df      = 1.0

    tasks = generate_tasks(n_tasks)
    global_deadline, _ = compute_deadlines(n_tasks, df)
    expected_mk = get_expected_makespan(n_tasks)

    # Inject hibernation of the HIGH-RISK VM at 20% of expected makespan
    # This is the core experimental condition: m5.xlarge hibernates,
    # P-BurstHADS already moved long tasks off it, BurstHADS didn't
    # Multiple hibernations guarantee m5.xlarge is caught busy
    # First at t=10% (early, VM definitely loaded)
    # Second at t=35% (mid-execution, catches queued tasks)
    # This matches paper's approach of testing under sustained pressure
    avg_exec_on_m5 = 225.0 / PER_CORE_SPEED["m5.xlarge"]
    hib_time = [
        max(1.0, avg_exec_on_m5 * 0.5),   # ~28s: first task still running
        max(1.0, avg_exec_on_m5 * 2.5),   # ~141s: second wave
    ]

    print(f"Global deadline  : {global_deadline:.0f}s")
    print(f"Expected makespan: {expected_mk:.0f}s")
    hib_str = [f"{h:.0f}s" for h in hib_time]
    print(f"Hibernation times: {hib_str}  (HIGH-RISK m5.xlarge VM)")
    print(f"Avg exec_time    : "
          f"{sum(t.exec_time for t in tasks)/len(tasks):.0f}s")
    print()

    print("VM pools:")
    print("  HADS:               c5.large(spot) + m5.xlarge(spot) + c5.large(od)")
    print("  BurstHADS/P-Burst:  c5.large(spot) + c5.xlarge(spot) + "
          "m5.xlarge(spot) + t3.large(burs) + c5.large(od)")
    print()

    print("=== All schedulers (with hibernation) ===")
    results = {}
    for label, cls, vm_builder in [
        ("HADS",        HADS,        build_vms_dburst),
        ("BurstHADS",   BurstHADS,   build_vms_dburst),
        ("D-BurstHADS", RBurstHADS,  build_vms_dburst),
    ]:
        random.seed(42)
        m = run_simulation(cls, tasks, global_deadline,
                           hibernation_time=hib_time,
                           vm_builder=vm_builder,
                           hibernate_high_risk=True)
        s = m.summary()
        results[label] = s
        extra = ""
        if hasattr(m.scheduler if hasattr(m,'scheduler') else None,
                   'provisioning_summary'):
            pass
        print(f"  {label:12s}: cost=${s['total_cost']:.6f}  "
              f"makespan={s['makespan']:.1f}s  "
              f"misses={s['deadline_misses']}")

    print()
    print("=== Ordering check ===")
    hc = results["HADS"]["total_cost"]
    bc = results["BurstHADS"]["total_cost"]
    dc = results["D-BurstHADS"]["total_cost"]

    print(f"  HADS > BurstHADS:    "
          f"{'PASS' if hc > bc else 'FAIL'}  "
          f"({(hc-bc)/hc*100:+.1f}%)")
    print(f"  BurstHADS > D-Burst: "
          f"{'PASS' if bc > dc else 'FAIL'}  "
          f"({(bc-dc)/bc*100:+.1f}%)")
    print(f"  HADS > D-BurstHADS:  "
          f"{'PASS' if hc > dc else 'FAIL'}  "
          f"({(hc-dc)/hc*100:+.1f}%)")
