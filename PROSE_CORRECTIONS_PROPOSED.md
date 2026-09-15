# Prose corrections, proposed: every claim now false, with corrected wording

Prepared for the owner. **No listed file has been edited.** This covers
CLAUDE.md, PAPER_SKELETON.md, RESULTS_PACK.md (the strings in
`experiments/results_pack.py`), FIGURE_SPEC.md, the committed `paper/paper.tex`,
and `paper/fig/FIGURES.md`.

**Numbers.** Every corrected number comes from the regenerated RESULTS_PACK.md
on tag `freeze-fix21`, code fingerprint `2439a00d7f74`, and is cited
[table, row]. The pack tables used:

| table | covers |
|---|---|
| T1 | limits on, 75 fully feasible cells |
| T2 | limits off, 80 cells |
| T2b | limits on against off, over the same cells |
| T5 | missed tasks |
| T6 | infeasible runs |
| T9 | validation against TCC23 |
| T16 | the deviation register |

**Register counts.** They are given twice:
- **DEVIATIONS.md as it stands:** 29 rows.
- **DEVIATIONS_PROPOSED.md, if adopted:** 39 rows.

**Order.** Items are listed by file and line. Section 7 lists every composed
or derived percentage.

---

## 1. CLAUDE.md

| # | line | now false | why | corrected wording |
|---|---|---|---|---|
| C1 | 118–124 | "The HADS / Burst-HADS `_attempt_ondemand_fallback` deadline test (start + omega + remaining / speed) omits the overhead … unmeasured, not fixed: DEVIATIONS U10." | Fix 20 added (1 + ovh). Measured, it changes no run. | "The HADS / Burst-HADS `_attempt_ondemand_fallback` deadline test is start + ω + remaining / speed × (1 + ovh) (fix 20). It changes no run in either catalogue, because no dearer on-demand type runs a task faster than a cheaper one (DEVIATIONS U10)." |
| C2 | 114–118 (addition) | The key mechanics state the overhead rule but not the deploy-time rule that now governs every prediction. | Fixes 18 and 21. | Add: "Every VM a scheduler launches, at t = 0 or mid-run, runs no task before launch + STARTUP_LATENCY (45 s, `VM.ready_time`), and every finish predicted on it charges that, as execution does (fixes 18, 21). Only the builder's initial fleet, deployed by a primary schedule at t = 0, is exempt." |
| C3 | 139–141 | "launches forced past a limit are counted in `limit_overrides`: 0 in all 7,200 freeze-sweep runs" | The sweep named is superseded. | "… 0 in all 7,200 runs of the freeze-fix21 sweep." |
| C4 | 142–144 | "the spot limit binds only on R-BurstHADS's launches — and at the freeze it binds hard (Where the result stands)" | Stale reference. | "… binds only on R-BurstHADS's launches: at freeze-fix21 it reaches a launch limit in 2,281 of its 2,400 runs [T7], and the spot limit is what selects 1,401 of its 1,453 mid-run burstables [T24]." |
| C5 | 145–147 | "At the freeze only HADS is ever infeasible (10 runs, n=100 at the DF=0.25 deadline floor)" | 110 runs since fix 21. | "At freeze-fix21 only HADS is ever infeasible: 110 runs, all in the five n = 100, DF = 0.25 cells at the deadline floor [T6]. Its t = 0 on-demand VMs now wait their deploy time; with limits off every one is feasible (DEVIATIONS E14)." |
| C6 | 150–155 (addition) | The deadline paragraph omits that the floor has no deploy-time term. | Fix 21 makes it bind on feasibility. | Add: "The floor has no deploy-time term; since fix 21 it binds HADS's feasibility in the n = 100, DF = 0.25 cells (DEVIATIONS E14)." |
| C7 | 167–171 | "stage / Attempt 3 launches new on-demand capacity" | Burst-HADS's Attempt 3 first takes any on-demand pool VM with launch room, launched or not. | "… stage / Attempt 3 launches on-demand capacity: Burst-HADS's first takes any on-demand pool VM with launch room, launched or not (DEVIATIONS U11), then a fresh VM from M^o." |
| C8 | 185–296 | The fix history ends at 16, and "FROZEN at tag `freeze-round-b` (code fingerprint `4f08f48ac35c`). No further simulator changes" | The freeze was lifted twice. | Add fixes 17a (saturation re-placement deadline test), 18 (boot delay of R-BurstHADS's provisioned spot VMs), 19 (checkpoint credits executed progress), 20 (overhead in the fallback test; inert) and 21 (deploy time for every VM a scheduler launches: 21a mid-run, 21b R-BurstHADS's mid-run burstables, 21c t = 0 decisions). Then: "**FROZEN at tag `freeze-fix21` (code fingerprint `2439a00d7f74`).** The freeze of `freeze-round-b` was lifted twice by the owner, for fixes 17a–20 (`freeze-fix20`, `d40a1c917c63`) and for fix 21, each pre-registered and adopted only when the adopted code reproduced its variant row for row." |
| C9 | 55–57 | "After the freeze, a newly found defect goes into the paper's limitations, not into the code." | Superseded twice. | "After `freeze-round-b` the owner lifted the freeze for fixes 17a–20 and for fix 21. From `freeze-fix21` a newly found defect goes into DEVIATIONS.md as a limitation." |
| C10 | 305–311 | "**Freeze sweep** (tag `freeze-round-b`, fingerprint `4f08f48ac35c`) … `sweep_raw_4f08f48ac35c.jsonl` … `sweep_variant_nocap_4f08f48ac35c.*` … reproduces all 450 checkpoint runs (`checkpoint_freeze_df*`). No launch was forced past a limit." | Superseded files. | "**Freeze sweep** (tag `freeze-fix21`, fingerprint `2439a00d7f74`) … `sweep_raw_2439a00d7f74.jsonl`, `sweep_variant_nocap_2439a00d7f74.*`. The checkpoint harness check: 450 runs compared, 0 differ, 0 not in sweep (`checkpoint_fix21_df*`). No launch was forced past a limit." |
| C11 | 313–318 | "10 runs are infeasible, all HADS (2 seeds in each sc1–sc5 n=100 DF=0.25 cell) … all 80 cells with 28–30 seeds (Burst −18.0% / +20.0%, R −26.4% / +12.2%, R vs Burst −11.9% / −5.0%, dominance 44/80)" | New baseline. | "110 runs are infeasible, all HADS (22 of 30 seeds in each sc1–sc5 n = 100, DF = 0.25 cell). The tables are over the 75 cells where every scheduler is feasible in every seed; over all 80 cells with their feasible seeds: Burst −18.4% / +18.2%, R −26.0% / +11.5%, R vs Burst −11.3% / −4.3%, dominance 49/80 [T1 last row]." |
| C12 | 322–328 | Limits-on table (all 75: −19.1 / +21.3 / −27.9 / +12.9 / −12.7 / −5.4 / 44; DF rows). | New baseline. | Replace with T1's rows (Burst mk, Burst $, R mk, R $, R vs Burst mk, R vs Burst $, dominance), listed below the table. |
| C13 | 332–338 | Limits-off table (all 80: −18.1 / +21.9 / −31.0 / +2.6 / −17.8 / −14.6 / 69/80; DF rows). | New baseline. | Replace with T2's rows, listed below the table. |
| C14 | 340–342 | "By scenario, limits on, R-BurstHADS vs HADS (makespan / cost, 80 cells): sc1 −37.1% / +18.9% …" | New baseline. The per-scenario rows are over 15 fully feasible cells each, not 80. | "By scenario, limits on, R-BurstHADS vs HADS (makespan / cost; 15 fully feasible cells each) [T1]: sc1 −38.7% / +18.6%, sc2 −17.3% / +18.4%, sc3 −36.6% / +10.6%, sc4 −19.7% / +7.6%, sc5 −26.0% / +4.0%." |
| C15 | 344–348 | "Lifting it changes mainly R-BurstHADS: its cost lead over Burst-HADS grows from −5.4% to −14.6% and its misses vanish." | Compares 75 cells with 80 (see D3). Numbers superseded. "Misses vanish" implies the limit caused them. | "Lifting it changes mainly R-BurstHADS. Over the same 75 cells [T2b], its cost change vs Burst-HADS goes from −4.6% to −14.1% and its makespan change from −12.0% to −17.6%. Burst-HADS vs HADS moves from +19.0% to +20.3% cost. With limits off Burst-HADS and R-BurstHADS still miss 5 tasks between them, in the same floor cells [T5]." |
| C16 | 349–351 | "Burst-HADS is cheaper than HADS in 15 of 80 cells. R-BurstHADS ranges from −22.5% (sc4 n=200 DF=2.0) to +43.8% (sc1 n=50 DF=2.0) and is no more expensive than HADS in 18 of 75 cells." | New baseline. | "Burst-HADS is cheaper than HADS in 16 of 80 cells. R-BurstHADS ranges from −23.5% (sc4 n=300 DF=2.0) to +41.6% (sc4 n=50 DF=1.0) and is no more expensive than HADS in 18 of 75 cells [T3]." |
| C17 | 352 | "HADS's makespan is 62–100% of D; it never exceeds D." | New baseline. | "HADS's makespan is 63–100% of D (cell means; 47–100% per run); it never exceeds D." |
| C18 | 354–359 | "HADS 0; Burst-HADS 1 task in one run; **R-BurstHADS 109 tasks, in 4.3% of runs and 22 of 80 cells** … R-BurstHADS is the only scheduler that misses deadlines, and only when the instance limit blocks its provisioning." | New baseline. The attribution is wrong. | "HADS 0; Burst-HADS 6 tasks in 6 runs; R-BurstHADS 5 tasks in 5 runs [T5]. With limits off, Burst-HADS 2 and R-BurstHADS 3. Every one is in the n = 100, DF = 0.25 floor cells: a hibernation rescue that no on-demand VM the fallback was allowed to launch could finish by D after its 45 s deploy time. With limits on, the faster types were at their launch limits; with limits off, every type failed the fallback's own deadline test (`diag_f21_misses.txt`, `diag_f21_misses_nocap.txt`). At `freeze-round-b`, R-BurstHADS's 109 misses came from its own saturation response re-placing tasks without a deadline test, with the launch limit only as the trigger (DEVIATIONS R1; fix 17a removed 108 of them)." |
| C19 | 361–372 | Contribution statement: "Burst-HADS buys −19.1% makespan for +21.3% cost … R-BurstHADS delivers −27.9% for +12.9% — about 1.5× the makespan benefit at about 60% of the premium — and is 12.7% faster and 5.4% cheaper … dominating it … in 44 of 75 cells. The advantage lives at DF ≥ 1.0 (−15.9% / −4.3% and −28.9% / −14.9%); at DF ≤ 0.5 … cost the same (−1.3%, −0.0%) and R-BurstHADS alone misses deadlines, in 4.3% of runs overall" | New baseline. "1.5× … 60%" is derived (D1). "Alone misses" is false. | "Burst-HADS buys −19.6% makespan for +19.0% cost over HADS. R-BurstHADS delivers −27.7% for +11.8%. It is 12.0% faster and 4.6% cheaper than Burst-HADS on average and dominates it on both axes in 49 of 75 cells [T1 all]. The advantage lives at DF ≥ 1.0 (−14.7% / −3.1% and −28.5% / −14.3%). At DF 0.25 and 0.5 the two are within about a point (−1.2% / −0.8% and −1.0% / +0.7%); at DF 0.5 R-BurstHADS is significantly slower than Burst-HADS in 7 cells and dearer in 6 [T1 DF rows]." |
| C20 | 374–389 | The dead-claims list is incomplete. | Superseded headlines. | Add:<ul><li>the freeze-round-b headline (−27.9% / +12.9% vs HADS, −12.7% / −5.4% vs Burst-HADS, 44/75);</li><li>the freeze-fix20 headline (−27.6% / +13.7%, −12.4% / −4.7%, 42/75);</li><li>"109 missed tasks in 4.3% of runs";</li><li>"the misses are caused by the launch cap";</li><li>"R-BurstHADS is the only scheduler that misses";</li><li>"−5.4% → −14.6% when limits are lifted" (mixed cell sets);</li><li>"about 1.5× the makespan benefit at about 60% of the premium";</li><li>"R-BurstHADS's advantage reverses at n = 300".</li></ul> |
| C21 | 530–538 | "At the freeze … Table 9 cost change vs HADS +18.8% … makespan reduction 22.2%, J60 35.4%, ED200 5.3%; hibernation premium HADS +105%, Burst-HADS +40%. Without hibernation … J60 −70.9% … +87% … Limits on and off agree to a tenth of a point." | New baseline. | "At freeze-fix21 (`diag_cost_gap_fix21_nocap_c3`, `_capped_c3`) [T9]:<ul><li>Table 9 cost change vs HADS +17.9% limits off, +17.7% limits on (TCC23 +1.92%);</li><li>makespan reduction 21.8% (25.87%), J60 34.5% (40.10%), ED200 4.8% (10.24%);</li><li>hibernation premium HADS +110% (+95%), Burst-HADS +43% (+25%);</li><li>without hibernation J60 −70.9% vs HADS (−44.4%) and cost change +87% (+67%) [T8].</li></ul>Limits on and off agree within 0.15 points." |
| C22 | 556–562 | "At the freeze R-BurstHADS's deadline misses all disappear with instance limits off (RESULTS_PACK T5, T7)." | Superseded attribution. | "At freeze-fix21 R-BurstHADS misses 5 tasks with limits on and 3 with limits off, and Burst-HADS 6 and 2. All are floor-cell rescues that no on-demand VM the fallback could launch would finish by D after its deploy time [T5, `diag_f21_misses.txt`, `diag_f21_misses_nocap.txt`]." |
| C23 | 563–565 | "`limit_overrides` is 0 in all 7,200 freeze-sweep runs." | Sweep named. | "… 0 in all 7,200 freeze-fix21 runs." |
| C24 | 572–580 | "Round C is analysis only (owner, after the freeze): no simulation runs of any kind." | Superseded by the post-freeze rounds. | "Round C began as analysis only; the owner then reopened the simulator twice (fixes 17a–20, 21), under pre-registration, and re-froze it at `freeze-fix21`." |
| C25 | 585–586 | "`paper/` is entirely pre-fix. Rebuild from the freeze sweep" | Freeze named. | "… Rebuild from the freeze-fix21 sweep …" |
| C26 | 587–588 | "Figures: the owner has a separate unresolved issue with graph generation. **Do not generate figures until they raise it.**" | Resolved: six figures are built by `experiments/make_figures.py`. | "Figures: six single-column figures are built from RESULTS_PACK.md by `experiments/make_figures.py` per `experiments/FIGURE_SPEC.md`; the current set is `experiments/fig_fix21/`." |
| C27 | 609, 611 | `--checkpoint-tag freeze`; `--base-fp 4f08f48ac35c` | New tag. | `--checkpoint-tag fix21`; `--base-fp 2439a00d7f74` |

**C12, limits on [T1]:** Burst mk, Burst $, R mk, R $, R vs Burst mk, R vs Burst $, dominance.

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ | dominance |
|---|---|---|---|---|---|---|---|
| all 75 | −19.6% | +19.0% | −27.7% | +11.8% | −12.0% | −4.6% | 49/75 |
| DF 0.25 (15) | −7.4% | +8.3% | −8.4% | +7.4% | −1.2% | −0.8% | 9/15 |
| DF 0.5 (20) | −6.1% | +17.4% | −7.0% | +18.1% | −1.0% | +0.7% | 9/20 |
| DF 1.0 (20) | −14.8% | +19.6% | −26.8% | +14.7% | −14.7% | −3.1% | 12/20 |
| DF 2.0 (20) | −47.0% | +27.9% | −63.7% | +6.1% | −28.5% | −14.3% | 19/20 |

**C13, limits off [T2]:** same columns.

| cells | Burst mk | Burst $ | R mk | R $ | R vs Burst mk | R vs Burst $ | dominance |
|---|---|---|---|---|---|---|---|
| all 80 (80) | −18.4% | +19.5% | −30.1% | +2.4% | −16.5% | −13.2% | 67/80 |
| DF 0.25 (20) | −5.6% | +10.5% | −7.1% | +7.5% | −1.6% | −2.6% | 11/20 |
| DF 0.5 (20) | −6.1% | +18.8% | −12.0% | −1.7% | −6.2% | −16.6% | 18/20 |
| DF 1.0 (20) | −14.8% | +20.8% | −33.3% | +2.1% | −22.2% | −14.9% | 19/20 |
| DF 2.0 (20) | −47.0% | +27.9% | −67.9% | +1.5% | −35.9% | −18.6% | 19/20 |

---

## 2. PAPER_SKELETON.md

| # | line | now false | why | corrected wording |
|---|---|---|---|---|
| S1 | 18 | "premium reduced by 8.4 points, **39%** of it" / "by about two fifths" | New baseline. The share is derived (D4). | "cuts the cost premium over HADS from 19.0% to 11.8%, by 7.1 points [T1 all]" |
| S2 | 19 | "Burst-HADS also misses **1 task in 1 run** … 'the only scheduler with more than a single missed task: 109 tasks in 104 runs, against 1 and 0'" | New baseline. | "R-BurstHADS misses 5 tasks in 5 runs, Burst-HADS 6 in 6, HADS none [T5 on], all in the n = 100, DF = 0.25 floor cells" |
| S3 | 20 | Row on "caused by the cap", "93.5% … clean runs" | Now definitive. | "At freeze-round-b the misses were caused by R-BurstHADS's own saturation response, re-placing tasks without a deadline test, with the launch limit only as the trigger (fix 17a removed 108 of 109; DEVIATIONS R1). At freeze-fix21, R-BurstHADS reached a launch limit in 2,281 of 2,400 runs [T7]. Its remaining misses (5 with limits on, 3 off) are floor-cell rescues that no on-demand VM the fallback could launch would finish by D after its 45 s deploy time." |
| S4 | 21 | "27.9% … 12.7% … 26.4% and 11.9%" | New baseline. | "27.7% and 12.0% over the 75 fully feasible cells; 26.0% and 11.3% over all 80 [T1 all; T1 last row]" |
| S5 | A2 | "27.9% below HADS's and 12.7% below Burst-HADS's" | New baseline. | "27.7% … 12.0% [T1 all]" |
| S6 | A3 | "12.9% against Burst-HADS's 21.3% … 5.4% cheaper" | New baseline. | "11.8% against Burst-HADS's 19.0% … 4.6% cheaper [T1 all]" |
| S7 | A4 | "17.8% faster and 14.6% cheaper than Burst-HADS, dominating it in 69 of 80 cells" | New baseline. | "16.5% faster and 13.2% cheaper than Burst-HADS, dominating it in 67/80 cells [T2 all]" |
| S8 | A5 | "misses 109 deadline tasks in 4.3% of runs (HADS 0, Burst-HADS 1); all disappear without limits" | New baseline. | "Under limits R-BurstHADS misses 5 deadline tasks and Burst-HADS 6, all at the tightest (floor) deadlines, and HADS none; without limits they miss 3 and 2 [T5]" |
| S9 | A6 | "Burst-HADS +18.8% vs HADS against the published +1.92%" | New baseline. | "+17.9% [T9]" |
| S10 | A7, C3, 5.8 | "29 deviations: 10 corrected, 13 … design, 1 retained addition, 5 open"; "29-row deviation register"; the 5.8 lists | Pending the register decision. | If the proposed register is adopted: "39 rows: 15 corrected (B1, U1, U2, U4, U6, H2, H4, E1, E3, E10, E11, E12, R1, R4, R5), 15 design, 7 open (B2, B5, U11, E6, E8, E13, R2), 1 retained addition (U5), 1 inert (U10) [T16]". Until then T16 counts 29. |
| S11 | 1.2 | "19.1% faster than HADS for 21.3% more cost" | New baseline. | "19.6% faster … 19.0% more cost [T1 all]" |
| S12 | 3.2 | "Tier 3: deadline-sized reactive provisioning (Theorem 2)" | Theorem 2's sizing runs in the saturation response. | "Tier 3: one new instance for the task: spot if it passes the finish, spare-time and launch-limit tests, otherwise a burstable if it finishes by D (in practice chosen by the spot launch limit, [T24]); every such instance waits T_start. Theorem 2 sizes the saturation response after a hibernation." |
| S13 | 3.3 | "Everything else is Burst-HADS unchanged, including its Attempts 1–3." | Needs the deploy-time rule and fix 17a. | "… including its Attempts 1–3, which the saturation response also uses since fix 17a; every instance any scheduler launches waits T_start (fixes 18, 21)." |
| S14 | 4.1 | "Simulator frozen at tag `freeze-round-b`, code fingerprint `4f08f48ac35c`; no simulator change after the tag" | Superseded. | "Simulator frozen at tag `freeze-fix21`, fingerprint `2439a00d7f74`. The freeze was lifted twice for pre-registered fixes (17a–20, 21), each adopted only when the adopted code reproduced its variant row for row [T17]." |
| S15 | 4.4 | "Deadline floor 339.7 s, binding at DF 0.25 for n = 100" | Incomplete. | "… binding at n = 50 for DF ≤ 0.5 and n = 100 for DF 0.25; it has no deploy-time term (DEVIATIONS E14)" |
| S16 | 4.6 (addition) | The metrics omit deploy time. | Fixes 18, 21. | Add: "Every instance a scheduler launches, at t = 0 or mid-run, runs no task for T_start = 45 s after launch and is billed from launch; the initial pool is exempt." |
| S17 | 4.7 | "the adopted code reproduces the adopted variant in 1,440 / 1,440 validation rows and 2,400 / 2,400 sweep rows [T17]" | Incomplete. | "… and fixes 17a–20 and 21 each reproduce their variant in 2,400 / 2,400 export rows and 7,200 / 7,200 sweep rows [T17]" |
| S18 | 5.2 | "−70.9 / −59.8 / −50.7 / −0.1% against −44.4 / −42.1 / −28.8 / −11.8%" | New baseline. | "−70.9 / −61.5 / −52.7 / +1.6% [T8]" |
| S19 | 5.3 | "+18.80% vs +1.92%; makespan reduction 22.18% vs 25.87%; J60 35.43% vs 40.10%; ED200 5.28% vs 10.24% … within 0.14 points" | New baseline. | "+17.86% (limits off; +17.71% on) vs +1.92%; 21.78% vs 25.87%; J60 34.49% vs 40.10%; ED200 4.79% vs 10.24% … within 0.15 points [T9]" |
| S20 | 5.4 | "+40% vs +25%; HADS's is +105% vs +95%" | New baseline. | "+43% vs +25%; HADS's +110% vs +95% [T9]" |
| S21 | 5.6 | Hibernations per run "sc1 5.3 / 3.7 … sc2 8.9 / 8.6 … sc3 5.9 / 4.2 … sc4 18.4 / 16.1 … sc5 12.4 / 10.2" | New baseline. | "sc1 5.3 / 3.7, sc2 8.9 / 8.7, sc3 5.9 / 4.3, sc4 18.6 / 16.3, sc5 12.4 / 10.3 [T9]" |
| S22 | 5.7 | "+38.7% → +18.8%, 14.7% → 22.2%, +94% → +40% [T11, first and freeze rows]" | New baseline. | "+38.7% → +17.9%, 14.7% → 21.8%, Burst-HADS premium +94% → +43% [T11, first and current rows]" |
| S23 | 6.1 | "−19.1% / +21.3%; −27.9% / +12.9%; −12.7% / −5.4%; 44 of 75" | New baseline. | "−19.6% / +19.0%; −27.7% / +11.8%; −12.0% / −4.6%; 49 of 75 [T1 all]" |
| S24 | 6.2 | "faster … in 45 cells and slower in 9; cheaper in 29 and dearer in 7" | New baseline. | "faster in 42, slower in 9; cheaper in 25, dearer in 8 [T1 all]" |
| S25 | 6.3 | "DF 2.0 −28.9% / −14.9% (17/20); DF 1.0 −15.9% / −4.3% (10/20); DF 0.5 −1.4% / −0.0% (10/20; … slower in 7 … dearer in 6); DF 0.25 −1.8% / −1.3%" | New baseline. | "DF 2.0 −28.5% / −14.3% (19/20); DF 1.0 −14.7% / −3.1% (12/20); DF 0.5 −1.0% / +0.7% (9/20; significantly slower in 7, dearer in 6); DF 0.25 −1.2% / −0.8% (9/15) [T1 DF rows]" |
| S26 | 6.4 | "sc1 (−18.9% / −9.8%) and sc3 (−17.4% / −9.5%), smallest in sc4 (−7.5% / −1.0%) and sc2 (−7.7% / −1.3%)" | New baseline. | "sc1 (−18.3% / −9.3%) and sc3 (−16.2% / −8.2%); smallest in sc4 (−7.6% / −0.7%) and sc2 (−7.5% / −0.6%) [T1 scenario rows]" |
| S27 | 6.5 | "n = 50 −19.2% / −12.3% (17/20); n = 300 −6.5% / +1.1% (5/20)" | New baseline. There is no longer a cost reversal at n = 300. | "n = 50 −17.1% / −9.9% (14/20); n = 300 −7.6% / −0.2% (12/20) [T1 n rows]" |
| S28 | 6.7 | "R-BurstHADS 109 tasks in 104 of 2,400 runs (4.3%; 0.028% of tasks), 80 of them at DF 0.5; Burst-HADS 1 task in 1 run; HADS none. Worst cells sc4 and sc5 at n = 300, DF 0.5, 15 tasks each" | New baseline. | "R-BurstHADS 5 tasks in 5 of 2,400 runs; Burst-HADS 6 in 6; HADS none, in 2,290 feasible runs. All in the n = 100, DF = 0.25 cells [T5]" |
| S29 | 6.8 | "**Cause** … Every missing run had reached a launch limit (104/104; c5.xlarge spot in 103, t3.large in 101), but 93.5% of R-BurstHADS's clean runs had too." | Superseded. | "**Cause.** Each missed task is a hibernation rescue at t = 96–262 s in a floor cell: the c5 on-demand types were at their launch limits, and the remaining type could not finish the task by D after its 45 s deploy time (`diag_f21_misses.txt`). With limits off, 5 tasks still miss, where every type fails the fallback's own deadline test (`diag_f21_misses_nocap.txt`) [T5 off]. The earlier 109 misses were R-BurstHADS's saturation response (fix 17a)." |
| S30 | 6.9 | "10, all HADS (sc1–sc5, n = 100, DF 0.25, seeds 1 and 24 …) … Over all 80 cells …: R vs H −26.4% / +12.2%, R vs B −11.9% / −5.0%, 44/80" | New baseline. | "110, all HADS, in the five n = 100, DF = 0.25 cells (22 of 30 seeds each, D = 339.7 s at the floor); each is feasible with limits off. Burst-HADS and R-BurstHADS are feasible in all 2,400 runs [T6]. Over all 80 cells: R vs H −26.0% / +11.5%, R vs B −11.3% / −4.3%, 49/80 [T1 last row]." |
| S31 | 7.1 | "−17.8% makespan / −14.6% cost, dominating 69 of 80 cells; significantly faster in 70 and slower in none; cheaper in 59, dearer in 4. Vs HADS −31.0% / +2.6%." | New baseline. | "−16.5% / −13.2%, dominating 67/80; significantly faster / slower 66 / 0; cheaper / dearer 53 / 4. Vs HADS −30.1% / +2.4% [T2 all]" |
| S32 | 7.2 | "its cost lead over Burst-HADS is −5.4% with limits [T1 all] and −14.6% without [T2 all]; its premium over HADS +12.9% → +2.6%. Burst-HADS barely changes: −19.1% / +21.3% → −18.1% / +21.9%" | Mixed cell sets (D3). New baseline. | "Over the same 75 cells [T2b]: R-BurstHADS vs Burst-HADS cost −4.6% → −14.1%, makespan −12.0% → −17.6%; its premium over HADS +11.8% → +1.9%. Burst-HADS vs HADS −19.6% / +19.0% → −19.5% / +20.3%." |
| S33 | 7.3 | "R vs B −1.4% / −0.0% with limits, −7.2% / −18.2% (19/20) without" | New baseline. The two DF 0.5 rows cover the same 20 cells. | "R vs B −1.0% / +0.7% with limits [T1 DF 0.5], −6.2% / −16.6% (18/20) without [T2 DF 0.5]" |
| S34 | 7.4 | "No missed tasks and no infeasible runs for any scheduler [T5 off; T6]" | Re-check on the new baseline. | "5 missed tasks and 0 infeasible runs, limits off [T5 off; T6]" |
| S35 | L2 | "Under limits it is the only scheduler with more than one missed task (109 vs 1 vs 0) [T5], and its cost lead shrinks from −14.6% to −5.4% [T2, T1]" | Both false; mixed cells. | "Launch limits suppress most of R-BurstHADS's advantage: over the same cells its cost change vs Burst-HADS is −14.1% without limits and −4.6% with them [T2b]; under limits it and Burst-HADS both miss tasks in the floor cells (5 and 6) [T5]." |
| S36 | L5 | "Open deviations B2, B5, U10, E6, E8, including one unmeasured one (U10)" | U10 is measured and inert; there are new open items. | If the proposed register is adopted: "Open deviations B2, B5, U11, E6, E8, E13, R2; the effects of U11 and E13 are unmeasured [T16]" |
| S37 | F3 | "Measuring the unmeasured deviation U10 [T16]." | Measured: inert. | "Measuring U11 (Attempt 3's candidate loop) and E13 (pre-checkpoint remaining work in rescue tests)." |
| S38 | App. D | "tag `freeze-round-b`, fingerprint `4f08f48ac35c` … pre-registration `experiments/round_a_grid_plan.md`" | Superseded. | "tag `freeze-fix21`, fingerprint `2439a00d7f74` … pre-registrations `experiments/round_a_grid_plan.md`, `fix17_plan.md`, `fix18_20_plan.md`, `fix21_plan.md`" |

---

## 3. RESULTS_PACK.md (strings in `experiments/results_pack.py`)

The regenerated pack's numbers are current. These fixed strings are not:

| # | table | now false | corrected wording |
|---|---|---|---|
| P1 | T11 caption | "How the baseline changes adopted in Rounds A–B moved the validation numbers." | "How the baseline changes adopted in Rounds A–B and in the post-freeze rounds (fixes 17a–20, 21) moved the validation numbers." |
| P2 | T12 second table, row label | "kept (frozen code)" | The numbers come from the Round A grid files (`519c868a99f9`), not from frozen code. Use "kept (Round A grid)". |
| P3 | T13, row label | "frozen code (three on-demand types)" | "freeze-round-b (three on-demand types)" |
| P4 | T16 | Counts DEVIATIONS.md (29 rows) | Correct as generated. It becomes 39 only if DEVIATIONS_PROPOSED.md is adopted; no string change. |
| P5 | Key numbers | "premium reduced by … points" | Correct since this pass, which marks the share as derived (see D4). Listed so it is not re-derived elsewhere. |

---

## 4. FIGURE_SPEC.md

| # | line | now false | corrected wording |
|---|---|---|---|
| F1 | 25–29 | "HADS appears as a real series only in Fig. 6, where the quantity is absolute." | "HADS never appears as a series: it is the zero line (Figs. 1–5) or the origin (Fig. 6)." |
| F2 | 65–68 | Fig. 1: "give the all-80-cell figures (26.4 % and 11.9 %) too" | "(26.0 % and 11.3 %)" [T1 last row] |
| F3 | 70–72 | Fig. 2: "Shows R-BurstHADS crossing from dearer to cheaper as slack grows." | "Shows R-BurstHADS's cost premium over HADS peaking at DF 0.5 (+18.1 %, level with Burst-HADS's +17.4 %) and falling to +6.1 % at DF 2.0, while Burst-HADS's rises to +27.9 % [T1 DF rows]." Against Burst-HADS, R-BurstHADS is dearer only at DF 0.5 (+0.7 %). |
| F4 | 79–81 | Fig. 4: "Source T5/T1 … where the sc1 weakness is visible" | "Source T1. sc1 carries R-BurstHADS's highest premium over HADS (+18.6 %) and its largest lead over Burst-HADS (−9.3 %); its weakest scenarios against Burst-HADS are sc2 (−0.6 %) and sc4 (−0.7 %)." |
| F5 | 83–86 | Fig. 5: "the advantage *reverses*: at n = 300 R-BurstHADS is 1.1 % more expensive than Burst-HADS" | "the advantage shrinks with n: R-BurstHADS vs Burst-HADS cost −9.9 % at n = 50 to −0.2 % at n = 300 [T1 n rows]; it no longer reverses." |
| F6 | 88–91 | Fig. 6: "missed tasks. Grouped bars … HADS 0, Burst-HADS 1 task in 1 run, R-BurstHADS 109 tasks in 104 runs." | "**Fig. 6 — limits on against limits off.** One plane: cost change vs HADS (x), makespan change vs HADS (y), over the 75 cells fully feasible in both settings. Source T2b. HADS is the origin. Each scheduler has a filled marker (on), a hollow marker (off) and an arrow labelled with the shift in points." |
| F7 | 98–99 | "an **8.4-point cut — 39 % of the premium**" | "a 7.1-point cut, from 19.0 % to 11.8 % [T1 all]". The share of the premium is a ratio of averages (D4); use it only if labelled as derived. |
| F8 | 100–101 | "R-BurstHADS is **not the only scheduler that misses**: Burst-HADS misses 1 task in 1 run under limits. HADS misses none." | "Under limits Burst-HADS misses 6 tasks and R-BurstHADS 5, all in the n = 100, DF = 0.25 floor cells; HADS misses none [T5]." |
| F9 | 102–105 | "The misses are **not demonstrably 'caused by the cap'** … The evidence is the matched counterfactual" | "The 109 misses at freeze-round-b were **caused by R-BurstHADS's own saturation response**, which re-placed tasks without a deadline test; reaching the launch limit only triggered it (DEVIATIONS R1; fix 17a removed 108 of 109). The misses that remain, with limits on or off, are floor-cell rescues that no on-demand VM the fallback could launch would finish by D after its deploy time." |
| F10 | 106–107 | "27.9 % and 12.7 % are over the 75 fully feasible cells; over all 80 they are 26.4 % and 11.9 %." | "27.7 % and 12.0 % … 26.0 % and 11.3 %" |
| F11 | 108–109 | "significantly **slower** than Burst-HADS in 9 cells and **dearer** in 7" | "slower in 9, dearer in 8 [T1 all]" |
| F12 | 115–123 | Table map: "T6 (validation failures)"; "headline results, limits on / off, ± 95 % CI \| T1, T2"; "experiment grid \| T2" | "T6 infeasible runs"; "headline results \| T1, T2, T2b" (no CIs on the aggregates; per-cell CIs are T3, T4); "experiment grid \| pack header". Add the post-freeze tables T18–T25. |
| F13 | 125 | "T6 (validation failures) and the deviation register are not padding." | "T8–T11 and T14 (validation failures) and the deviation register are not padding." |

---

## 5. `paper/fig/FIGURES.md`

| # | now false | corrected |
|---|---|---|
| G1 | The whole file records the `freeze-round-b` figures: "Simulator untouched (`freeze-round-b`, fingerprint `4f08f48ac35c`)", every plotted number, and Fig. 6 as missed tasks. | It is accurate only as a record of the PDFs now in `paper/fig/`. When those are replaced by `experiments/fig_fix21/`, regenerate the record from the new pack. Items to change: Fig. 1 numbers (T1 all); Figs. 2–5 as F3–F5; Fig. 6 as F6; "Without limits there is no reversal: n = 300 R vs B −12.8 %" becomes −13.1% [T2 n = 300]; the "Conflicts" list items 1, 3, 5, 6 as F3, F5, F12. |

---

## 6. `paper/paper.tex` (committed; pre-fix throughout)

Every quantitative claim predates fixes 1–21, and most qualitative results
claims do too. The design sections need targeted corrections; the results,
validation, discussion and conclusion need rewriting from the pack.

| # | line | now false | corrected wording |
|---|---|---|---|
| T1 | 33–42 | Abstract: "2,700 simulation runs … six workload sizes … reduces makespan relative to Burst-HADS by 26.0–39.8% in every scenario … cost-neutral at k_h=1, 12.5% cheaper at k_h=3, and 14.3–64.3% cheaper at k_h=5. All three schedulers complete 100% of tasks, but only the two burstable-aware schedulers meet the deadline in every configuration. We first validate our HADS and Burst-HADS implementations … reproducing the reported ordering and the direction and magnitude of its cost differences." | "Across 7,200 runs per launch-limit setting (five hibernation scenarios, four workload sizes, four deadline factors, 30 seeds, three schedulers), under provider launch limits R-BurstHADS's makespan is 27.7% below HADS's and 12.0% below Burst-HADS's. Its cost premium over HADS is 11.8%, against Burst-HADS's 19.0%; it is 4.6% cheaper than Burst-HADS and dominates it on both axes in 49 of 75 cells. Without launch limits it is 16.5% faster and 13.2% cheaper than Burst-HADS. Its cost advantage grows with deadline slack and is largest at the lowest interruption rate. Our re-implemented baselines do not reproduce the source work's hibernation cost result (Burst-HADS +17.9% vs HADS against the published +1.92%), so we report a controlled comparison with a documented fidelity audit, not a reproduction." |
| T2 | 96–98 | Contribution: "We **validate our baseline implementations** against the published results" | "We audit the fidelity of our baseline re-implementations against the published results and disclose where they do not reproduce them" |
| T3 | 99–103 | Contribution: "R-BurstHADS's cost advantage grows monotonically with the interruption rate while its makespan advantage is essentially rate-independent" | "R-BurstHADS's advantage over Burst-HADS grows with deadline slack and is largest at the lowest interruption rate (cost −9.3% in sc1 and −8.2% in sc3 at k_h = 1; −0.6% in sc2 and −0.7% in sc4 at k_h = 5) [T1]" |
| T4 | 208–211 | "Both launch instances of the most cost-efficient spot type present in the scheduler's own pool" | "Both launch spot instances of the most cost-efficient spot type in the scheduler's own pool; the per-task tier falls back to a burstable when a spot instance cannot be launched within the limits or would breach the spare-time margin. Every launched instance, spot or burstable, is usable only after T_start." |
| T5 | 161 vs 387 | ω is defined as the "checkpoint overhead fraction", but Algorithm 5 Attempt 4 uses it as deploy time ("start_ij + e_ij + ω < D"). | Attempt 4: "if t + T_start + e_ij(1 + ω) ≤ D, within the type's launch limit" |
| T6 | 324–325 | Algorithm 3: "C_react ← n_v ē (r_o/s_o − r_s/s_s)", "C_proact ← T_start r_s + (ē/s_s) r_s" | "C_react ← n_v ē (r_o/θ_o − r_s/θ_s), θ = s·nvc (fix 6)"; "C_proact ← T_start r_s + ε, ε = 0 (fix 7)" |
| T7 | 356 | Algorithm 4: "W ← Σ remaining time of t_i" | "W ← Σ remaining time of t_i × (1 + ω) (fix 10)". Also add: "if D − t ≤ 2 T_start the new instances are burstables (θ = s_b)". |
| T8 | 376–387 | Algorithm 5: "Attempt 0 … that finishes t_i before D"; "Attempt 3 (R-BurstHADS): DeadlineAwareProvision"; "Attempt 4: new vm_j ∈ M^o, cheapest first" | Attempt 0: "a provisioned replacement passing CheckMigration (memory, D, CPU credits, spare-time margin)". Attempt 3: "provision one instance for t_i: spot if it passes the finish, spare-time and launch-limit tests, else a burstable if it finishes by D; ready at t + T_start. DeadlineAwareProvision runs after a hibernation, not per task." Attempt 4: "an on-demand instance with launch room (Burst-HADS first takes any on-demand pool instance, launched or not, DEVIATIONS U11), else a new one from M^o, cheapest type first, per T5". |
| T9 | 397–399 | Algorithm 6: "non-burstable vm_j ∈ BR, most loaded first"; "Slack(t_i, vm_k, D) > 0" | "on-demand sources first, then spot"; "CheckMigration(t_i, vm_k, D)" |
| T10 | 264 | Algorithm 2: "∀ vm_j ∈ M^o already running, cheapest first" | "∀ on-demand vm_j with launch room, cheapest first" (the code does not require it to be running) |
| T11 | 418–420 | "three instances of each spot type, one burstable instance seeding the elastic pool M^b, and one on-demand instance as the template for the unbounded pool M^o" | "three instances of each spot type, one burstable template for M^b, and three on-demand templates (c5.large, c5.xlarge, m5.xlarge) for M^o, within the reference account limits: 5 launches per type and 20 per market, burstables counting as on-demand" |
| T12 | 421–424 | "Per-instance-type hibernation rates use the source work's worst-case parameterisation … for m5.xlarge and a low nominal rate for the remaining spot types" | "Under the source work's scenarios every spot instance, of every type and including replacements launched mid-run, is hibernated at λ_h = k_h/D; the per-type declared rates are read only by Theorem 1's trigger" |
| T13 | 429 | "\|T\| ∈ {10,20,50,100,200,300}" | "\|T\| ∈ {50, 100, 200, 300}" |
| T14 | 440–444 | Table II: c5.xlarge s_j = 4, m5.xlarge s_j = 4, t3.large s_j = 2, a single on-demand row (c5.large) | per-core speeds c5.large 2, c5.xlarge 2, m5.xlarge 1.7, t3.large 1.7 (one slot); on-demand rows c5.large $0.085, c5.xlarge $0.170, m5.xlarge $0.192 [T15] |
| T15 | 461 | "All reported experiments use DF=1." | "DF ∈ {0.25, 0.5, 1.0, 2.0}; D is floored at 339.7 s, binding at n = 50 for DF ≤ 0.5 and n = 100 for DF = 0.25" |
| T16 | 472 | "In total the evaluation comprises 2,700 simulation runs." | "7,200 runs with the reference launch limits, and the same 7,200 without" |
| T17 | 504–506 | Table IV: "DF 1.0"; no launch limits | "DF 0.25, 0.5, 1.0, 2.0"; add "launch limits: 5 per type, 20 per market" |
| T18 | 515–559, 543–544 | §VI and its figure: "We therefore first reproduce the published comparison … Our HADS implementation lands within a few percent of the published makespans … The direction of the cost difference is reproduced in every job and its magnitude closely in three of four …"; Table III's numbers; "The most plausible explanation is capacity" | "Without hibernation our HADS lands within 1–3% of Table 7's makespans for J60–J100 (2,330 / 2,350 / 2,356 s against 2,290 / 2,295 / 2,332 s) and 8% below for ED200. Our Burst-HADS does not: makespan change vs HADS −70.9 / −61.5 / −52.7 / +1.6% against −44.4 / −42.1 / −28.8 / −11.8% [T8]. Under hibernation its cost change vs HADS is +17.9% against the published +1.92%, its makespan reduction 21.8% against 25.87%, and its hibernation premium +43% against +25% [T9]. The baselines are not a validated reproduction [T14 for causes ruled out]." Remove the capacity explanation, which was never measured. |
| T19 | 582–588 | "All three schedulers completed 100% of tasks in all 30 configurations … Burst-HADS and R-BurstHADS met the deadline in every configuration. HADS missed in three" | "Under launch limits HADS misses no task in its 2,290 feasible runs but finds no feasible primary schedule in 110 (the n = 100, DF = 0.25 floor cells) [T6]. Burst-HADS misses 6 tasks and R-BurstHADS 5, all in those cells [T5]. Without limits they miss 2 and 3, in the same cells [T5 off]." |
| T20 | 592–598 | "At \|T\|=300 … Burst-HADS is faster than HADS, by between 1.1% (sc2) and 24.9% (sc3), and more expensive, by between 1.7% (sc4) and 16.1% (sc1). The ordering weakens as the workload shrinks …" | "Burst-HADS is 19.6% faster than HADS and 19.0% dearer on average over the 75 fully feasible cells, dearer at every n: from +28.0% at n = 50 to +11.5% at n = 300 [T1 n rows]." |
| T21 | 624–629 | "R-BurstHADS is 26.0–39.8% faster than Burst-HADS in every scenario, with no systematic relationship to k_h" | "R-BurstHADS's makespan is 7.5% (sc2) to 18.3% (sc1) below Burst-HADS's, larger at k_h = 1 (sc1 −18.3%, sc3 −16.2%) than at k_h = 5 (sc2 −7.5%, sc4 −7.6%) [T1 scenario rows]" |
| T22 | 631–641 | "the cost advantage scales monotonically with the interruption rate … +0.5% in sc1, −0.5% in sc3 … 12.5% cheaper … 14.3% … 64.3% cheaper … the strongest evidence that the effect is mechanistic" | "R-BurstHADS vs Burst-HADS cost by scenario: sc1 −9.3%, sc3 −8.2% (k_h = 1); sc5 −4.3% (k_h = 3); sc2 −0.6%, sc4 −0.7% (k_h = 5) [T1]. The advantage falls as the interruption rate rises." Delete the mechanistic-evidence sentence. |
| T23 | 564–684 | Figures `fig1_makespan_cost`, `fig6_makespan_variability`, `fig4_speedup`, `fig9_deadline_utilisation`, `fig2_rburst_advantage`, `fig8_kh_sensitivity`, `fig5_tradeoff`, `fig7_heatmap`, `fig3_cost_per_task`: `figure*` and multi-panel. Captions include "The cost advantage is monotone in k_h", "R-BurstHADS occupies the faster region; Burst-HADS clusters near the baseline", "HADS consumes its budget almost entirely; R-BurstHADS retains headroom". | Replace with the six single-column figures (`experiments/fig_fix21/`, FIGURE_SPEC.md). The captions are false: the advantage falls with k_h (T22); Burst-HADS is 19.6% faster than HADS, not near the baseline [T1]. |
| T24 | 686–750 | Tables V and VI (n = 10–300, DF = 1, pre-fix means) | Replace from T1 and T3 (limits on) and T2 and T4 (limits off). |
| T25 | 756–762 | "When the contribution is inert … identical to Burst-HADS in most cells … 33% cheaper" | Not measured on the current code: the validation runs in the pack (`diag_cost_gap`) cover HADS and Burst-HADS only. Remove, or re-measure first. |
| T26 | 766–773 | "Neither extension dominates HADS on cost. HADS is the cheapest of the three in most configurations … HADS is the only scheduler in the study that misses a deadline, and it is 26–40% slower than R-BurstHADS at every workload size above 100 tasks." | "R-BurstHADS is no more expensive than HADS in 18 of 75 cells, and Burst-HADS is cheaper than HADS in 16 of 80 [T3]. HADS misses no task. R-BurstHADS's makespan is 25.7–29.9% below HADS's at every n [T1 n rows]." The "26–40% slower" wording is a derived reversal (D7). |
| T27 | 777–787 | Limitations: "the per-instance-type differentiation of hibernation rates … is a modelling choice of this study"; "the baseline reproduction degrades on the largest job" | "Table 9 scenarios hibernate every spot instance at the same rate, so per-type risk is never exercised"; "the baselines do not reproduce the source work under hibernation at any job size [T9]". Add the launch limits, the deadline floor (E14), the retained guard (U5) and the deviation register. |
| T28 | 794–798 | Conclusion: "Across 2,700 simulation runs it reduced makespan relative to Burst-HADS by 26.0--39.8\% … from cost-neutral at k_h=1 to 64.3\% cheaper … Both extensions met the deadline in every configuration, where HADS did not." | Restate the T1 headline sentence as written for the abstract. "Under launch limits Burst-HADS and R-BurstHADS miss 6 and 5 tasks at the tightest deadlines; HADS misses none but has no feasible schedule in 110 runs there." |

---

## 7. Composed or derived percentages (not computed directly from the runs)

| # | where | figure | how it was obtained | status |
|---|---|---|---|---|
| D1 | CLAUDE.md 363 | "about 1.5× the makespan benefit at about 60% of the premium" | Ratios of two averaged percentages: 27.9 / 19.1 and 12.9 / 21.3. | Derived. Drop it, or state it as a ratio of averages. |
| D2 | CLAUDE.md 377, 382–383 (dead claims) | "about 1.9× … 37% of the premium", "2.2× … a sixth of the premium" | Same derivation. | Derived (already dead). |
| D3 | CLAUDE.md 346–347; PAPER_SKELETON 7.2, L2 | "−5.4% … to −14.6%" | Two directly computed averages over different cell sets (75 limits on, 80 limits off), read as a change. | Not like for like. Use T2b. |
| D4 | PAPER_SKELETON 18; FIGURE_SPEC 98–99; `paper/fig/FIGURES.md` Fig. 1; RESULTS_PACK key numbers | "39% of the premium", "about two fifths" | (B $ vs H − R $ vs H) / B $ vs H: a ratio of two averages. The point difference itself is valid, since over identical cells it equals the mean per-cell difference. | Derived. The pack now labels it so. |
| D5 | The owner's derivation of Burst-HADS vs HADS from R-BurstHADS vs HADS and vs Burst-HADS | — | Composed from two averaged percentages. | Replaced by the directly computed key number: −19.6% makespan, +19.0% cost, limits on [T1 all]. |
| D6 | `paper/paper.tex` 770–771 | "HADS … 26–40% slower than R-BurstHADS" | Reverses the direction of an averaged change. A −x% change of R-BurstHADS vs HADS is not "HADS x% slower"; per cell that would be x / (1 − x). | Derived. Use R-BurstHADS vs HADS as computed [T1]. |
| D7 | `paper/paper.tex` Table V, 693–700, and abstract | "Makespan (%) +39.8 … +26.0" (a reduction printed positive), "mean over \|T\| ≥ 100" | An aggregation not in the pack; its source is not recorded. | Unverifiable and pre-fix. Replace from T1. |
| D8 | `paper/paper.tex` Fig. `fig4_speedup` | "Speedup relative to HADS" | Makespan ratios from a pre-fix pipeline. | Not in the pack. Remove or recompute from runs. |
| D9 | CLAUDE.md 340–342 | Per-scenario values labelled "80 cells" | The values are over 15 fully feasible cells per scenario. | Mislabelled cell set (C14). |

**Checked and computed directly from runs** (no action): every "% vs X" in
T1–T4, T2b, T8–T11, T14, T18, T19 and T23; the "0.14 points" in
PAPER_SKELETON 5.3, which is a difference of two directly computed
values; and CLAUDE.md's DF breakdowns.
