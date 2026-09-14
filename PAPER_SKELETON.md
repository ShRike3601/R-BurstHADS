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
| "cuts Burst-HADS's cost premium roughly in half, 21.3% to 12.9%" | premium reduced by 8.4 points, **39%** of it [Key numbers; T1 all, B $ vs H / R $ vs H] | "cuts the premium from 21.3% to 12.9%, by about two fifths" |
| "the ONLY scheduler that misses deadlines under limits" | Burst-HADS also misses **1 task in 1 run** (DF 0.25); HADS 0 [T5 on] | "the only scheduler with more than a single missed task: 109 tasks in 104 runs, against 1 and 0" |
| "every one caused by the cap blocking its own provisioning" | the same runs with limits off miss **0** tasks [T5 off; T7]. Every missing run had reached a launch limit (104/104; c5.xlarge spot in 103), but so had **93.5%** of R-BurstHADS's runs without a miss [T7] | "all 109 disappear when the same runs are repeated without launch limits" (the counterfactual is the evidence, not the limit flag) |
| "27.9% faster than HADS and 12.7% faster than Burst-HADS" | over the **75** cells where every scheduler is feasible in every seed; over all 80 cells with available seeds: 26.4% and 11.9% [T1 all; T1 last row] | state "75 cells" and give the 80-cell values in a footnote |

---

## Abstract — claims

- A1. Three schedulers (HADS, Burst-HADS, R-BurstHADS) in one discrete-event simulator, frozen before the final runs; 80 cells × 30 seeds × 3 schedulers = 7,200 runs per launch-limit setting [pack header].
- A2. Under provider launch limits, R-BurstHADS's makespan is 27.9% below HADS's and 12.7% below Burst-HADS's [T1 all: R mk vs H −27.9%, R mk vs B −12.7%].
- A3. Its cost premium over HADS is 12.9% against Burst-HADS's 21.3% [T1 all: R $ vs H +12.9%, B $ vs H +21.3%]; 5.4% cheaper than Burst-HADS [T1 all: R $ vs B −5.4%].
- A4. Without launch limits: 17.8% faster and 14.6% cheaper than Burst-HADS, dominating it in 69 of 80 cells [T2 all].
- A5. **Negative.** Under limits R-BurstHADS misses 109 deadline tasks in 4.3% of runs (HADS 0, Burst-HADS 1) [T5 on]; all disappear without limits [T5 off].
- A6. **Negative.** The re-implemented baselines do not reproduce TCC23's hibernation cost result: Burst-HADS +18.8% vs HADS against the published +1.92% [T9].
- A7. A fidelity audit documents 29 deviations from the published algorithms: 10 corrected, 13 deliberate design choices, 1 retained addition, 5 open [T16].

## 1. Introduction

- 1.1 Spot hibernation threatens deadlines; Burst-HADS rescues interrupted tasks onto burstable VMs. (no number)
- 1.2 Motivation claim: under launch limits Burst-HADS is 19.1% faster than HADS for 21.3% more cost [T1 all: B mk vs H, B $ vs H].
- 1.3 Contributions:
  - C1. R-BurstHADS: deadline-aware preemptive and reactive spot provisioning on top of Burst-HADS. (design, no number)
  - C2. A controlled comparison under two account regimes on the same 7,200 runs [T1, T2].
  - C3. A fidelity audit: validation against TCC23 [T8, T9, T10], ruled-out causes [T14], the trajectory of adopted corrections [T11], a 29-row deviation register [T16], decisions pre-registered in a commit before the runs they decided (`experiments/round_a_grid_plan.md`, ec52967) [T12 caption], adopted code verified row for row [T17].
  - C4. Negative results reported in full [T5, T6, T7, T9].
- 1.4 Non-claim: this is not a reproduction of TCC23 [T9 all rows].

## 2. Background and related work

- 2.1 HADS (CC21) and Burst-HADS (TCC23). TCC23 reports a 25.87% makespan reduction and a +1.92% cost change for Burst-HADS vs HADS under hibernation [T9, TCC23 column], and −44.4% / +67.2% on J60 without hibernation [T8 J60, TCC23 columns].
- 2.2 Burstable economics depend on the catalogue: in TCC23's catalogue a burst-mode task costs 0.83× the same task alone on a new on-demand VM; in our sweep catalogue (current AWS prices) 1.15× [T15, bullet lines].
- 2.3 Related work on spot scheduling and burstable instances. (no numbers)

## 3. R-BurstHADS

- 3.1 Tier 0: pre-provisioned replacement spot VMs (Theorem 1), gated by Burst-HADS's own migration checks. (no number)
- 3.2 Tier 3: deadline-sized reactive provisioning (Theorem 2). (no number)
- 3.3 Everything else is Burst-HADS unchanged, including its Attempts 1–3. (no number)

## 4. Experimental method

- 4.1 Simulator frozen at tag `freeze-round-b`, code fingerprint `4f08f48ac35c`; no simulator change after the tag [pack header].
- 4.2 Two catalogues: sweep (c5.large / c5.xlarge / m5.xlarge spot and on-demand, t3.large) and validation (TCC23 Table 3) [T15].
- 4.3 Scenarios: TCC23 sc1–sc5 (kh, kr) = (1,0), (5,0), (1,5), (5,5), (3,2.5) [T9 by-scenario column 1]; n ∈ {50, 100, 200, 300}; DF ∈ {0.25, 0.5, 1.0, 2.0}; 30 seeds [pack header].
- 4.4 Deadline floor 339.7 s, binding at DF 0.25 for n = 100 [T6 D column; T3 `*` rows].
- 4.5 Launch limits from the reference implementation's account: 5 per instance type per market, 20 per market, burstables counted as on-demand [pack header]. Limits-off control: the same 7,200 runs [T2 source].
- 4.6 Metrics. Cost billed per second from launch to shutdown or hibernation (TCC23 §3.1). Cell = (scenario, n, DF); percentages are ratios of cell means averaged over cells; paired per-seed 95% CIs for R-BurstHADS vs Burst-HADS [T1 caption]. Two miss measures: missed tasks and share of runs with any miss [T5 caption]. Infeasible runs reported with cause [T6].
- 4.7 Decision discipline: every change measured first as a counterfactual; the one open design question decided by a rule committed before its runs [T12 caption]; the adopted code reproduces the adopted variant in 1,440 / 1,440 validation rows and 2,400 / 2,400 sweep rows [T17].

## 5. Fidelity audit: what our re-implementations do and do not reproduce

- 5.1 HADS without hibernation lands near TCC23's makespans for J60–J100: 2330 vs 2290 s, 2350 vs 2295 s, 2356 vs 2332 s; ED200 2365 vs 2580 s [T8, HADS mk columns].
- 5.2 Burst-HADS without hibernation does not: makespan change vs HADS −70.9 / −59.8 / −50.7 / −0.1% against −44.4 / −42.1 / −28.8 / −11.8% [T8, mk change columns]; its J60 cost matches ($0.110 vs $0.112) [T8 J60].
- 5.3 Under hibernation neither published aggregate is reproduced: cost change +18.80% vs +1.92%; makespan reduction 22.18% vs 25.87%; J60 35.43% vs 40.10%; ED200 5.28% vs 10.24% [T9]. Limits on and off agree within 0.14 points [T9, two "ours" columns].
- 5.4 The residual gap is Burst-HADS's hibernation premium, +40% vs +25%; HADS's is +105% vs +95% [T9].
- 5.5 Ruled out as causes [T14]:
  - aggregation: +38.7% (TCC23's definition), +36.6% pooled, +41.8% per run, +42.4% median, against +1.9%;
  - billing rule: 900 s quantisation +30.1%, billing from launch +40.4%, TCC23 §3.1 rule +42.5%, pre-fix billing +22.9% but its no-hibernation cost change is +83.4% against +50.8%;
  - EBS charges: +37.5%.
- 5.6 Our runs see more hibernations than TCC23 reports: per run sc1 5.3 / 3.7 vs 1.67, sc2 8.9 / 8.6 vs 5.83, sc3 5.9 / 4.2 vs 4.50, sc4 18.4 / 16.1 vs 8.75, sc5 12.4 / 10.2 vs 3.41 [T9 by scenario]. TCC23 does not state the spot pool size those counts depend on (DEVIATIONS E4, E8) — see Future work.
- 5.7 The corrections adopted during the audit moved the validation toward TCC23: cost change +38.7% → +18.8%, makespan reduction 14.7% → 22.2%, Burst-HADS premium +94% → +40% [T11, first and freeze rows].
- 5.8 Deviation register: 29 rows — corrected B1, U1, U2, U4, U6, H2, H4, E1, E3, E10; open B2, B5, U10, E6, E8; retained addition U5 [T16].
- 5.9 The retained addition (U5, a proactive-burstable guard) kept by the pre-registered rule: removing it turns 85 Burst-HADS and 92 R-BurstHADS runs from no missed task to at least one, against 0 and 3 the other way [T12].
- 5.10 The three-type on-demand catalogue alone removed the baselines' deadline misses on the main sweep (seeds 0–9): HADS 2,533 → 0, Burst-HADS 1,981 → 0, R-BurstHADS 1,090 → 43 missed tasks; infeasible runs 250 / 250 / 250 → 5 / 0 / 0 [T13].

## 6. Results under provider launch limits

- 6.1 Headline [T1 all]: Burst-HADS −19.1% makespan / +21.3% cost vs HADS; R-BurstHADS −27.9% / +12.9%; R-BurstHADS vs Burst-HADS −12.7% / −5.4%; dominates in 44 of 75 cells.
- 6.2 Significance [T1 all]: R-BurstHADS significantly faster than Burst-HADS in 45 cells and slower in 9; cheaper in 29 and dearer in 7.
- 6.3 The advantage needs slack [T1 DF rows]: R vs B at DF 2.0 −28.9% / −14.9% (17/20 dominated); DF 1.0 −15.9% / −4.3% (10/20); DF 0.5 −1.4% / −0.0% (10/20; significantly slower in 7 cells, dearer in 6); DF 0.25 −1.8% / −1.3%.
- 6.4 By scenario [T1 scenario rows]: largest in sc1 (−18.9% / −9.8%) and sc3 (−17.4% / −9.5%), smallest in sc4 (−7.5% / −1.0%) and sc2 (−7.7% / −1.3%).
- 6.5 By job size [T1 n rows]: n = 50 −19.2% / −12.3% (17/20); n = 300 −6.5% / +1.1% (5/20).
- 6.6 HADS finishes at 93% of D on average, 99% at DF 0.25 [T1 HADS mk/D column].
- 6.7 **Deadline misses** [T5 on]: R-BurstHADS 109 tasks in 104 of 2,400 runs (4.3%; 0.028% of tasks), 80 of them at DF 0.5; Burst-HADS 1 task in 1 run; HADS none. Worst cells sc4 and sc5 at n = 300, DF 0.5, 15 tasks each [T5 cell list].
- 6.8 **Cause** [T5 off; T7]: the same runs without launch limits miss no task. Every missing run had reached a launch limit (104/104; c5.xlarge spot in 103, t3.large in 101), but 93.5% of R-BurstHADS's clean runs had too.
- 6.9 **Infeasible runs** [T6]: 10, all HADS (sc1–sc5, n = 100, DF 0.25, seeds 1 and 24, D = 339.7 s at the floor): no primary schedule within D and the limits. Burst-HADS and R-BurstHADS are feasible in all 2,400 runs [T5 feasible runs]. Over all 80 cells with available seeds: R vs H −26.4% / +12.2%, R vs B −11.9% / −5.0%, 44/80 [T1 last row].
- 6.10 Per-cell means and 95% CIs: Appendix B [T3].

## 7. Results without launch limits

- 7.1 Headline [T2 all]: R-BurstHADS vs Burst-HADS −17.8% makespan / −14.6% cost, dominating 69 of 80 cells; significantly faster in 70 and slower in none; cheaper in 59, dearer in 4. Vs HADS −31.0% / +2.6%.
- 7.2 Headroom is what R-BurstHADS's cost advantage runs on: its cost lead over Burst-HADS is −5.4% with limits [T1 all] and −14.6% without [T2 all]; its premium over HADS +12.9% → +2.6%. Burst-HADS barely changes: −19.1% / +21.3% → −18.1% / +21.9% [T1 all, T2 all].
- 7.3 The DF 0.5 contrast: R vs B −1.4% / −0.0% with limits, −7.2% / −18.2% (19/20) without [T1, T2 DF 0.5 rows].
- 7.4 No missed tasks and no infeasible runs for any scheduler [T5 off; T6].
- 7.5 Per-cell means and 95% CIs: Appendix B [T4].

## 8. Threats to validity and limitations (placed before the conclusion, not after it)

- L1. **Not a reproduction.** TCC23's hibernation cost result is not reproduced (+18.8% vs +1.92%) and neither are its no-hibernation Burst-HADS makespans (J60 −70.9% vs −44.4%) [T9; T8]. Our comparisons are against our re-implementations as documented [T16].
- L2. **R-BurstHADS's advantage depends on launch headroom the provider may not give.** Under limits it is the only scheduler with more than one missed task (109 vs 1 vs 0) [T5], and its cost lead shrinks from −14.6% to −5.4% [T2, T1].
- L3. **The retained addition favours our comparison.** With the guard R vs B is −5.3% cost and 34/55 dominance on the grid; without it +5.8% and 14/55 [T12].
- L4. **The sweep catalogue penalises Burst-HADS's rescue mechanism.** At current AWS prices a burst-mode task costs 1.15× a lone task on new on-demand, against 0.83× in TCC23's catalogue [T15].
- L5. Open deviations B2, B5, U10, E6, E8, including one unmeasured one (U10) [T16].
- L6. Table 9 scenarios hibernate every spot VM at the same rate, so R-BurstHADS's per-type risk reasoning is never exercised; no result is attributed to risk awareness. (DEVIATIONS; no number)
- L7. One simulator, synthetic Table 6-style workloads, 30 seeds per cell [pack header].

## 9. Future work (one sentence each)

- F1. Spot pool size, which TCC23 does not state and on which its hibernation counts depend (DEVIATIONS E4, E8).
- F2. Re-running the sc1 provisioning and replacement-use diagnostics on the frozen code.
- F3. Measuring the unmeasured deviation U10 [T16].
- F4. Heterogeneous per-type hibernation rates, so that Theorem 1's risk reasoning is exercised.

## 10. Conclusion

- Restates A2–A6 with the same citations; no new numbers.

## Appendices

- A. DEVIATIONS.md, verbatim [T16 summarises it].
- B. Per-cell means and 95% CIs, limits on and off [T3, T4]; infeasible runs [T6].
- C. Validation detail: Table 7 [T8], Table 9 aggregates and scenarios [T9], cell by cell [T10], ruled-out causes [T14], audit trajectory [T11].
- D. Reproducibility: tag `freeze-round-b`, fingerprint `4f08f48ac35c`, the Sources table of RESULTS_PACK.md (file hashes and commits), `experiments/results_pack.py`, pre-registration `experiments/round_a_grid_plan.md` [T12 caption, T17].
