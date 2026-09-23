# Paper skeleton — R-BurstHADS

**Framing.** A controlled comparison of three schedulers re-implemented in one
frozen simulator, with a documented fidelity audit. **Not a reproduction** of
Teylo et al. (TCC23). DEVIATIONS.md is an appendix: the disclosure is part of
the contribution.

**Rules for this skeleton.** Every number is a cell of `RESULTS_PACK.md`, cited
as [table, row, column]. No number appears here that is not in the pack. No
prose yet. No figures.

---

## Wording checks against the brief (resolve before drafting)

| brief says | the pack says | use instead |
|---|---|---|
| "cuts Burst-HADS's cost premium roughly in half, 21.3% to 12.9%" | the premium falls from 19.0% to 11.8%, by 7.1 points [T1 all]. The share of the premium is a ratio of two averages and is derived, not measured | "cuts the cost premium over HADS from 19.0% to 11.8%, by 7.1 points [T1 all]" |
| "the ONLY scheduler that misses deadlines under limits" | R-BurstHADS misses 5 tasks in 5 runs, Burst-HADS 6 in 6, HADS none [T5 on] | "R-BurstHADS misses 5 tasks in 5 runs, Burst-HADS 6 in 6, HADS none, all in the n = 100, DF = 0.25 floor cells" |
| "every one caused by the cap blocking its own provisioning" | at `freeze-round-b` the misses came from R-BurstHADS's own saturation response re-placing tasks without a deadline test; the launch limit was only the trigger (fix 17a removed 108 of 109; DEVIATIONS R1). At freeze-fix21 it reaches a launch limit in 2,281 of 2,400 runs [T7] | "the remaining misses (5 with limits on, 3 off) are floor-cell rescues that no on-demand VM the fallback could launch would finish by D after its 45 s deploy time" |
| "27.9% faster than HADS and 12.7% faster than Burst-HADS" | 27.7% and 12.0% over the **75** cells where every scheduler is feasible in every seed; 26.0% and 11.3% over all 80 [T1 all; T1 last row] | state "75 cells" and give the 80-cell values in a footnote |
| the cost advantage, stated flat | it is conditional: on the retained U5 guard [T12], on launch headroom (−4.6% with limits, −14.1% without, same cells [T2b]), and on hibernation occurring at all (without it R-BurstHADS is 3.4% dearer, `u5_nohib_compare.txt`) | make **makespan** the unconditional claim (it holds in every configuration and regime, and is a wash at DF 0.5, 7 cells significantly slower against 6 faster [T1 DF=0.5]) and **cost scale-dependent**, anchored on the faithful DF 2.0 comparison rather than on the guard-kept sweep (A2, A3) |

---

## Abstract — claims

- A1. Three schedulers (HADS, Burst-HADS, R-BurstHADS) in one discrete-event simulator, frozen before the final runs; 80 cells × 30 seeds × 3 schedulers = 7,200 runs per launch-limit setting [pack header].
- A2. **Unconditional claim, makespan.** R-BurstHADS shortens makespan in every configuration and regime measured: 27.7% below HADS and 12.0% below Burst-HADS on the full sweep [T1 all], 11.0% below an unmodified Burst-HADS at DF 2.0 [T12c], and shorter with limits lifted, with the burstable tier disabled and with hibernation switched off. At DF 0.5 it is a wash (significantly slower in 7 cells against faster in 6) [T1 DF=0.5].
- A3. **Cost, anchored on the faithful DF 2.0 comparison and not general.** Against an unmodified Burst-HADS R-BurstHADS is 11.0% faster at 2.9% higher cost, with the penalty concentrated in small bags: +12.7% at n = 50 and +9.6% at n = 100, the same direction at DF 1.0 (+9.3 / +13.4%) and with limits off (+13.6 / +12.6%) [T12c]. **No n ≥ 200 operating point**: the gap is −8.8% at 200 and −2.0% at 300, non-monotone, so the threshold is an artefact. The sweep-wide faithful average is never cited (that baseline misses 91% of runs at DF 0.25). On the broader sweep, against our own Burst-HADS, it is 4.6% cheaper with a premium over HADS of 11.8% against 19.0% [T1 all] — that baseline carries the three departures, so the sweep is the broad picture, not the headline.
- A4. Without launch limits: 16.5% faster and 13.2% cheaper than Burst-HADS, dominating it in 67 of 80 cells [T2 all].
- A5. **Negative.** Under limits R-BurstHADS misses 5 deadline tasks and Burst-HADS 6, all at the tightest (floor) deadlines, and HADS none; without limits they miss 3 and 2 [T5].
- A6. **Negative.** The re-implemented baselines do not reproduce TCC23's hibernation cost result: Burst-HADS +17.9% vs HADS against the published +1.92% [T9].
- A7. A fidelity audit documents 40 deviations from the published algorithms: 15 corrected, 15 deliberate design choices, 8 open, 1 retained addition (U5), 1 inert (U10) [T16].
- A8. **Beyond scale (A3), the cost result carries three further conditions**, every one measured: on the retained U5 guard and the §3.2 step we never implemented [T12]; on launch headroom [T2b]; and on interruptions occurring, since without hibernation R-BurstHADS is 3.4% dearer than Burst-HADS and 8.9% faster (`u5_nohib_compare.txt`) — the expected behaviour of a scheduler that provisions in anticipation, and a sanity check on the method.

## 1. Introduction

- 1.1 Spot hibernation threatens deadlines; Burst-HADS rescues interrupted tasks onto burstable VMs. (no number)
- 1.2 Motivation claim: under launch limits Burst-HADS is 19.6% faster than HADS for 19.0% more cost [T1 all: B mk vs H, B $ vs H].
- 1.3 Contributions:
  - C1. R-BurstHADS: deadline-aware preemptive and reactive spot provisioning on top of Burst-HADS. (design, no number)
  - C2. A controlled comparison under two account regimes on the same 7,200 runs [T1, T2].
  - C3. A fidelity audit: validation against TCC23 [T8, T9, T10], ruled-out causes [T14], the trajectory of adopted corrections [T11], a 40-row deviation register [T16], decisions pre-registered in a commit before the runs they decided (`experiments/round_a_grid_plan.md`, ec52967; `fix17_plan.md`, `fix18_20_plan.md`, `fix21_plan.md`, `u5_remeasure_plan.md`, `ref_p2_plan.md`) [T12, T12b captions], adopted code verified row for row [T17].
  - C4. Negative results reported in full [T5, T6, T7, T9].
- 1.4 Non-claim: this is not a reproduction of TCC23 [T9 all rows].

## 2. Background and related work

- 2.1 HADS (CC21) and Burst-HADS (TCC23). TCC23 reports a 25.87% makespan reduction and a +1.92% cost change for Burst-HADS vs HADS under hibernation [T9, TCC23 column], and −44.4% / +67.2% on J60 without hibernation [T8 J60, TCC23 columns].
- 2.2 Burstable economics depend on the catalogue: in TCC23's catalogue a burst-mode task costs 0.83× the same task alone on a new on-demand VM; in our sweep catalogue (current AWS prices) 1.15× [T15, bullet lines].
- 2.3 Related work on spot scheduling and burstable instances. (no numbers)

## 3. R-BurstHADS

- 3.1 Tier 0: pre-provisioned replacement spot VMs (Theorem 1), gated by Burst-HADS's own migration checks. (no number)
- 3.2 Tier 3: one new instance for the task — spot if it passes the finish, spare-time and launch-limit tests, otherwise a burstable if it finishes by D (in practice the spot launch limit is what selects the burstable, in 1,401 of 1,453 firings [T24]); every such instance waits T_start. Theorem 2 sizes the saturation response after a hibernation.
- 3.3 Everything else is Burst-HADS unchanged, including its Attempts 1–3, which the saturation response also uses since fix 17a; every instance any scheduler launches waits T_start (fixes 18, 21). (no number)
- 3.4 **Ablation of the burstable branch** (pre-registered, `experiments/tier_off_plan.md`): disabling tier 3's burstable costs R-BurstHADS nothing in deadlines and buys nothing — the same 5 missed tasks and no run changing either way — while its cost against Burst-HADS improves from −4.6% to −9.1% and makespan from −12.0% to −14.0%, dominance 49 → 65 of 75 [`tier_off_compare.txt`]. The branch fires when the spot types are at their launch limits and substitutes an instance costing 1.15× the on-demand alternative it displaces [T15]. **Reported as a result; the tier is kept** (owner, 2026-09-23): the ablation was found after the fact and a self-serving design change does not follow from a clean measurement. Future work: the ablation indicates the tier belongs below rather than above the on-demand fallback, and it was not reordered after the measurement in order to keep the evaluation as pre-registered.

## 4. Experimental method

- 4.1 Simulator frozen at tag `freeze-fix21`, fingerprint `2439a00d7f74`. The freeze was lifted twice for pre-registered fixes (17a–20, 21), each adopted only when the adopted code reproduced its variant row for row [T17].
- 4.2 Two catalogues: sweep (c5.large / c5.xlarge / m5.xlarge spot and on-demand, t3.large) and validation (TCC23 Table 3) [T15].
- 4.3 Scenarios: TCC23 sc1–sc5 (kh, kr) = (1,0), (5,0), (1,5), (5,5), (3,2.5) [T9 by-scenario column 1]; n ∈ {50, 100, 200, 300}; DF ∈ {0.25, 0.5, 1.0, 2.0}; 30 seeds [pack header].
- 4.4 Deadline floor 339.7 s, binding at n = 50 for DF ≤ 0.5 and n = 100 for DF 0.25; it has no deploy-time term (DEVIATIONS E14) [T6 D column; T3 `*` rows].
- 4.5 Launch limits from the reference implementation's account: 5 per instance type per market, 20 per market, burstables counted as on-demand [pack header]. Limits-off control: the same 7,200 runs [T2 source].
- 4.6 Metrics. Cost billed per second from launch to shutdown or hibernation (TCC23 §3.1). Cell = (scenario, n, DF); percentages are ratios of cell means averaged over cells; paired per-seed 95% CIs for R-BurstHADS vs Burst-HADS [T1 caption]. Two miss measures: missed tasks and share of runs with any miss [T5 caption]. Infeasible runs reported with cause [T6]. Every instance a scheduler launches, at t = 0 or mid-run, runs no task for T_start = 45 s after launch and is billed from launch; the initial pool is exempt (Assumption 1).
- 4.7 Decision discipline: every change measured first as a counterfactual; the one open design question decided by a rule committed before its runs [T12b caption]; fixes 17a–20 and 21 each reproduce their variant in 2,400 / 2,400 export rows and 7,200 / 7,200 sweep rows [T17].

## 5. Fidelity audit: what our re-implementations do and do not reproduce

- 5.1 HADS without hibernation lands near TCC23's makespans for J60–J100: 2330 vs 2290 s, 2350 vs 2295 s, 2356 vs 2332 s; ED200 2365 vs 2580 s [T8, HADS mk columns].
- 5.2 Burst-HADS without hibernation does not: makespan change vs HADS −70.9 / −61.5 / −52.7 / +1.6% against −44.4 / −42.1 / −28.8 / −11.8% [T8, mk change columns]; its J60 cost matches ($0.110 vs $0.112) [T8 J60]. Removing the U5 guard brings J60 and J80 to −42.0% and −42.0%, against the published −44.4% and −42.1%, while the cost overshoots further (J60 +190% against +67%) [T12]: the published no-hibernation makespans are consistent with the unconditional move §3.2 describes.
- 5.3 Under hibernation neither published aggregate is reproduced: cost change +17.86% (limits off; +17.71% on) vs +1.92%; makespan reduction 21.78% vs 25.87%; J60 34.49% vs 40.10%; ED200 4.79% vs 10.24% [T9]. Limits on and off agree within 0.15 points [T9, two "ours" columns]. Removing the guard leaves the cost gap where it is (+18.07%), so the gap is not the guard's doing [T12].
- 5.4 The residual gap is Burst-HADS's hibernation premium, +43% vs +25%; HADS's is +110% vs +95% [T9].
- 5.5 Ruled out as causes [T14]:
  - aggregation: +38.7% (TCC23's definition), +36.6% pooled, +41.8% per run, +42.4% median, against +1.9%;
  - billing rule: 900 s quantisation +30.1%, billing from launch +40.4%, TCC23 §3.1 rule +42.5%, pre-fix billing +22.9% but its no-hibernation cost change is +83.4% against +50.8%;
  - EBS charges: +37.5%.
- 5.6 Our runs see more hibernations than TCC23 reports: per run sc1 5.3 / 3.7 vs 1.67, sc2 8.9 / 8.7 vs 5.83, sc3 5.9 / 4.3 vs 4.50, sc4 18.6 / 16.3 vs 8.75, sc5 12.4 / 10.3 vs 3.41 [T9 by scenario]. TCC23 does not state the spot pool size those counts depend on (DEVIATIONS E4, E8) — see Future work.
- 5.7 The corrections adopted during the audit moved the validation toward TCC23: cost change +38.7% → +17.9%, makespan reduction 14.7% → 21.8%, Burst-HADS premium +94% → +43% [T11, first and current rows].
- 5.8 Deviation register: 40 rows — 15 corrected (B1, U1, U2, U4, U6, H2, H4, E1, E3, E10, E11, E12, R1, R4, R5), 15 design (U3 among them, kept and disclosed), 8 open (B2, B5, U11, U12, E6, E8, E13, R2), 1 retained addition (U5), 1 inert (U10) [T16].
- 5.9 **Our Burst-HADS departs from TCC23's Algorithm 1 Part 2 and Algorithm 2 in three measured ways, all disclosed in the body, none adopted or removed.**
  - U5, the improvement guard on the proactive burstable move — our addition, kept by the pre-registered Round A rule, which still holds at freeze-fix21: removing it turns 974 Burst-HADS and 975 R-BurstHADS runs from no missed task to at least one, against 0 either way [T12, T12b].
  - U12, §3.2's step 2 (violators the burstables did not take go to the cheapest regular on-demand VMs), which our Part 2 does not implement: 575 of 2,400 runs leave 12,150 violators on spot past Dspot, all at DF ≤ 0.5 [T12, `diag_part2.txt`].
  - U3, Burst-HADS's Phase 3 on-demand fallback in the initial solution, where the reference raises "no solution": used in 905 of 2,400 runs, including all 150 runs of the floor cells; a reference-faithful Burst-HADS would be infeasible in exactly those runs, leaving 45 of the 75 cells, where R vs Burst-HADS is −19.1% makespan and −7.5% cost (`u3_exposure.txt`).
  - The sensitivity the paper cites is the reference-faithful one, not "the guard removed" alone, because that configuration is neither ours nor TCC23's [T12].
- 5.10 The three-type on-demand catalogue alone removed the baselines' deadline misses on the main sweep (seeds 0–9): HADS 2,533 → 0, Burst-HADS 1,981 → 0, R-BurstHADS 1,090 → 43 missed tasks; infeasible runs 250 / 250 / 250 → 5 / 0 / 0 [T13].

## 6. Results under provider launch limits

- 6.1 Headline [T1 all]: Burst-HADS −19.6% makespan / +19.0% cost vs HADS; R-BurstHADS −27.7% / +11.8%; R-BurstHADS vs Burst-HADS −12.0% / −4.6%; dominates in 49 of 75 cells. Absolute means behind the figures: T1b.
- 6.2 Significance [T1 all]: R-BurstHADS significantly faster than Burst-HADS in 42 cells and slower in 9; cheaper in 25 and dearer in 8.
- 6.3 The advantage needs slack [T1 DF rows]: R vs B at DF 2.0 −28.5% / −14.3% (19/20 dominated); DF 1.0 −14.7% / −3.1% (12/20); DF 0.5 −1.0% / +0.7% (9/20; significantly slower in 7 cells, dearer in 6); DF 0.25 −1.2% / −0.8% (9/15).
- 6.4 By scenario [T1 scenario rows]: largest in sc1 (−18.3% / −9.3%) and sc3 (−16.2% / −8.2%); smallest in sc4 (−7.6% / −0.7%) and sc2 (−7.5% / −0.6%).
- 6.5 By job size [T1 n rows]: n = 50 −17.1% / −9.9% (14/20); n = 300 −7.6% / −0.2% (12/20). The cost advantage no longer reverses at n = 300.
- 6.6 HADS finishes at 93% of D on average, 99% at DF 0.25 [T1 HADS mk/D column].
- 6.7 **Deadline misses** [T5 on]: R-BurstHADS 5 tasks in 5 of 2,400 runs; Burst-HADS 6 in 6; HADS none, in 2,290 feasible runs. All in the n = 100, DF = 0.25 cells.
- 6.8 **Cause.** Each missed task is a hibernation rescue at t = 96–262 s in a floor cell: the c5 on-demand types were at their launch limits, and the remaining type could not finish the task by D after its 45 s deploy time (`diag_f21_misses.txt`). With limits off, 5 tasks still miss, where every type fails the fallback's own deadline test (`diag_f21_misses_nocap.txt`) [T5 off]. The earlier 109 misses were R-BurstHADS's saturation response (fix 17a; DEVIATIONS R1).
- 6.9 **The tightest-deadline regime** [T6; `u3_exposure.txt`]: in the five n = 100, DF = 0.25 cells (D = 339.7 s at the floor, 150 runs) HADS finds no primary schedule within D and the launch limits in 110 runs, against 10 before deploy time was charged; Burst-HADS and R-BurstHADS complete all 150 and meet D in 144 and 145. Charging deploy time (Assumption 1) raised HADS's mean cost by 4.0% over its feasible runs, against +3.4% and +3.3% for the others, and made it infeasible in 100 more runs, each feasible once the limits are lifted. **Credit where it is due: Burst-HADS's and R-BurstHADS's feasibility here is an effect of our Phase 3 addition (DEVIATIONS U3), not of the published algorithm** — a reference-faithful Burst-HADS would be infeasible in all 150. Over all 80 cells with their feasible seeds: R vs H −26.0% / +11.5%, R vs B −11.3% / −4.3%, 49/80 [T1 last row].
- 6.10 **Against a faithful Burst-HADS — the cost anchor** [T12c, T30]. At DF ≥ 1.0 neither U3 nor U12 applies, so the U5 guard is the only departure left; at DF 2.0 the guard-free baseline also misses no deadline, making it an unmodified Burst-HADS that works — the most faithful comparison in the study. There R vs B is −11.0% makespan and **+2.9% cost**, dominance 10/20, significantly dearer in 9 cells and cheaper in 3. By bag size the cost gap runs +12.7% / +9.6% / −8.8% / −2.0% at n = 50/100/200/300, with dominance 0/5, 1/5, 5/5, 4/5. At DF 1.0: −6.4% / +5.0%, but the guard-free baseline misses in 145 of 600 runs there. **State this in our own voice**, next to the headline, rather than leaving it for a reviewer to find.
  - **No operating point at n ≥ 200.** The split is non-monotone and unexplained at the boundary; the per-n table is reported so the raggedness is visible, and nothing is claimed from it. What replicates, and is stated as our own negative finding, is the small-bag penalty: dearer at n = 50 and n = 100 in every faithful configuration measured.
  - **Mechanism: measured, not established** [T30]. Provisioned capacity is 33.6% utilised at n = 50 faithful, 77.8% at n = 200, 62.7% at n = 50 guard-kept, at a flat 13–15% share of cost. The pre-registered substitution reading predicted a larger burstable share (holds: 24.1% vs 2.8%) and a run-level association (fails: r = +0.17, 37/150 runs in the quadrant), so the mechanism stays open in the text.
  - **Post-hoc check on n = 300**, labelled because it would help us: lifting the launch limits moves n = 300 to −7.1% and n = 200 to −11.5%, narrowing the discrepancy from 6.8 to 4.4 points without closing it.
- 6.11 Per-cell means and 95% CIs: Appendix B [T3].

## 7. Results without launch limits

- 7.1 Headline [T2 all]: R-BurstHADS vs Burst-HADS −16.5% makespan / −13.2% cost, dominating 67 of 80 cells; significantly faster in 66 and slower in none; cheaper in 53, dearer in 4. Vs HADS −30.1% / +2.4%.
- 7.2 **Headroom is what R-BurstHADS's cost advantage runs on — the strongest finding in the work, and it gets its own called-out paragraph in the results text, not just a table row** (owner, 2026-09-23). Over the same 75 cells [T2b]: R-BurstHADS vs Burst-HADS cost −4.6% → −14.1%, makespan −12.0% → −17.6%, dominance 49 → 67; its premium over HADS +11.8% → +1.9%. Burst-HADS vs HADS barely moves: −19.6% / +19.0% → −19.5% / +20.3%. The provider's account limits, not the algorithm, decide how much of the advantage survives.
- 7.3 The DF 0.5 contrast: R vs B −1.0% / +0.7% with limits [T1 DF 0.5], −6.2% / −16.6% (18/20) without [T2 DF 0.5].
- 7.4 5 missed tasks (Burst-HADS 2, R-BurstHADS 3, all in the floor cells) and no infeasible runs [T5 off; T6].
- 7.5 Per-cell means and 95% CIs: Appendix B [T4].

## 8. Threats to validity and limitations (placed before the conclusion, not after it)

- L1. **Not a reproduction.** TCC23's hibernation cost result is not reproduced (+17.9% vs +1.92%) and neither are its no-hibernation Burst-HADS makespans (J60 −70.9% vs −44.4%) [T9; T8]. Our comparisons are against our re-implementations as documented [T16].
- L1b. **Our baseline's proactive burstable step is not TCC23's, and that is what makes it work at our deadlines.** Without the U5 guard our Burst-HADS reproduces the published no-hibernation makespans closely (J60 −42.0% against −44.4%, J80 −42.0% against −42.1%) but misses deadlines in 41% of sweep runs; the guard removes the misses and makes it far faster than published. The failure is not a hibernation effect: it is identical with hibernation switched off (40.8% of runs either way), and it is concentrated where deadlines are tight (91% of runs at DF 0.25, 48% at DF 0.5, 24% at DF 1.0, none at DF 2.0). TCC23 evaluates at D = 2,700 s, far looser than every cell here, so the guard is our adaptation to a harder experiment rather than a patch over a defect in the rescue path. The unexplained hibernation cost gap is independent of it (+17.9% with the guard, +18.1% without) [T12, `u5_nohib_compare.txt`].
- L2. **R-BurstHADS's advantage depends on launch headroom the provider may not give.** Over the same cells its cost change against Burst-HADS is −14.1% without limits and −4.6% with them [T2b]; under limits it and Burst-HADS both miss tasks in the floor cells (5 and 6) [T5].
- L3. **The retained addition favours our comparison.** With the guard R vs B is −5.3% cost and 34/55 dominance on the grid; without it +5.8% and 14/55 [T12].
- L3b. **The cost advantage does not hold against a faithful baseline at small bags.** At DF 2.0, the only regime where an unmodified Burst-HADS both follows §3.2 and meets its deadlines, R-BurstHADS is 2.9% dearer overall and 11.2% dearer at n ≤ 100, while remaining 11.0% faster [T12c]. Elastic provisioning has a fixed overhead that a small bag does not amortise. The makespan claim is unaffected.
- L4. **The sweep catalogue penalises Burst-HADS's rescue mechanism.** At current AWS prices a burst-mode task costs 1.15× a lone task on new on-demand, against 0.83× in TCC23's catalogue [T15].
- L5. Open deviations B2, B5, U11, U12, E6, E8, E13, R2; the effects of U11 and E13 are unmeasured [T16].
- L6. Table 9 scenarios hibernate every spot VM at the same rate, so R-BurstHADS's per-type risk reasoning is never exercised; no result is attributed to risk awareness. (DEVIATIONS; no number)
- L7. One simulator, synthetic Table 6-style workloads, 30 seeds per cell [pack header].

## 9. Future work (one sentence each)

- F1. Spot pool size, which TCC23 does not state and on which its hibernation counts depend (DEVIATIONS E4, E8).
- F2. Re-running the sc1 provisioning and replacement-use diagnostics on the frozen code.
- F3. Measuring U11 (Attempt 3's candidate loop) and E13 (pre-checkpoint remaining work in rescue tests); and reordering R-BurstHADS's tier 3 so the burstable sits below the on-demand fallback, which the pre-registered ablation indicates but which was deliberately not changed after seeing it [3.4].
- F4. Heterogeneous per-type hibernation rates, so that Theorem 1's risk reasoning is exercised.

## 10. Conclusion

- Restates A2–A6 with the same citations; no new numbers.

## Appendices

- A. DEVIATIONS.md, verbatim [T16 summarises it].
- B. Per-cell means and 95% CIs, limits on and off [T3, T4]; infeasible runs [T6].
- C. Validation detail: Table 7 [T8], Table 9 aggregates and scenarios [T9], cell by cell [T10], ruled-out causes [T14], audit trajectory [T11].
- D. Reproducibility: tag `freeze-fix21`, fingerprint `2439a00d7f74`, the Sources table of RESULTS_PACK.md (file hashes and commits), `experiments/results_pack.py`, pre-registrations `experiments/round_a_grid_plan.md`, `fix17_plan.md`, `fix18_20_plan.md`, `fix21_plan.md`, `tier_off_plan.md`, `u5_remeasure_plan.md`, `u5_nohib_plan.md`, `part2_plan.md`, `ref_p2_plan.md` [T12, T12b captions, T17].
