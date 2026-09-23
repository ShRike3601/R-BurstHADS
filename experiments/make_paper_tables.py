"""
Generate the paper's appendix tables from committed data only:

  * the deviation register index (every row of DEVIATIONS.md), and
  * the per-cell means with 95% confidence intervals, limits on and off,
    which are RESULTS_PACK.md's T3 and T4.

    python experiments\\make_paper_tables.py     (from the project root)

Output: paper/tables_generated.tex, \\input by paper.tex. Nothing here is
typed by hand, so the appendix cannot drift from the sweeps or the register.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import results_pack as rp

FP = "2439a00d7f74"
OUT = ROOT / "paper" / "tables_generated.tex"


# One-line measured effects, for the appendix column. A row appears here only
# when its effect has been measured; every phrase is a condensation of that
# row's "Measured effect" cell in DEVIATIONS.md, which carries the full text
# and the evidence file. Rows absent from this map print an em dash.
EFFECTS = {
    "B1": "20-cell cost change vs HADS +38.7 to +40.5%; launch-to-dispatch is 5.9% of Burst-HADS's no-hibernation cost",
    "B2": "charging EBS while hibernated: +38.7 to +37.5%; no cell moves by 3 points",
    "B3": "900 s quantisation: +38.7 to +30.1%, but no-hibernation cost change +55 to +79%",
    "B4": "undoing fixes 2-3: +38.7 to +22.9%, but J60 Burst-HADS no-hibernation cost $0.165 against Table 7's $0.112",
    "B5": "0.9-2.9% of HADS's cost in sc3-sc5, 0% of Burst-HADS's; removing it widens the gap to +40.7%",
    "U1": "produced every residual deadline miss in the fixes 1-10 sweep",
    "U2": "with U1 fixed, removed the remaining misses",
    "U3": "fires in 905 of 2,400 runs, all at DF <= 0.5, and in all 150 floor-cell runs; over the 45 cells a reference-faithful Burst-HADS could solve, R vs Burst-HADS is -19.1% makespan and -7.5% cost",
    "U4": "all of HADS's deadline misses before fix 8",
    "U5": "at DF 2.0, the only regime where the guard-free baseline meets every deadline, R vs Burst-HADS is -14.3% cost as frozen against +2.9% with TCC23 3.2 followed in full; removing the guard turns 974 clean Burst-HADS runs into missing ones, against 0 the other way. The sweep-wide faithful average is not cited: that baseline misses 91% of runs at DF 0.25 and 48% at 0.5",
    "U6": "hibernation makespan reduction 14.7 to 21.5%, 20-cell cost change +38.7 to +16.0%",
    "U8": "the reference's +inf sentinel gives near-identical results",
    "U10": "changes 0 of 7,200 runs, alone and within the combined set",
    "U11": "exposure 1,455 Burst-HADS and 759 R-BurstHADS mid-run launches; the effect of restricting the loop is unmeasured",
    "U12": "575 of 2,400 runs leave 12,150 violators on spot; implementing it alone takes Burst-HADS from 6 to 302 missed tasks and 4.1 points dearer against HADS, and changes nothing on TCC23's catalogue",
    "H2": "HADS launches 7.95 to 5.11 spot VMs per run and is 2.6% dearer and 3.5% slower against itself",
    "H4": "as U4",
    "E1": "infeasible runs 250/250/250 to 5/0/0; missed tasks 2,533/1,981/1,090 to 0/0/43",
    "E2": "fires in 23 of 7,200 runs, all at DF 0.25, one in a headline cell; 0 launches forced past a limit",
    "E3": "0.1 launches per run; not separable from E1, adopted in the same commit",
    "E4": "J60 makespan change vs HADS -71% at 3 spot copies, -78% at 5; Burst-HADS's hibernation premium +94/+47/+62% at 3/2/1",
    "E5": "both job generators reported side by side",
    "E6": "see B5",
    "E7": "a burst-mode task costs 1.15x a lone task on fresh on-demand in the sweep catalogue, 0.83x in TCC23's",
    "E8": "our runs see 1.3-3.6x TCC23's hibernations per run, flat across jobs",
    "E10": "Burst-HADS's hibernation premium +42 to +39%; sweep mean cost HADS -4.5%, Burst-HADS -2.2%, R-BurstHADS -2.9%",
    "E11": "runs changed 1,472/1,769/1,531 of 2,400; R vs Burst-HADS cost -5.39 to -5.30%",
    "E12": "36,574 of 42,249 launches started a task early before the fix; 0 of 42,623 after",
    "E13": "exposure 17.4/25.2/27.9 displaced running tasks per run; effect unmeasured",
    "E14": "HADS infeasible in 110 of the 150 floor-cell runs, against 10 before deploy time was charged; every one feasible with limits off",
    "R1": "108 of the 109 misses at freeze-round-b; fix 17a took them 109 to 1",
    "R2": "fix 17b: misses 109 to 1 but 337 of 2,400 runs change and dominance 44 to 43; rejected",
    "R3": "fix 17c: misses 109 to 73, 282 runs change; rejected",
    "R4": "6,661 early starts in 1,276 of 2,400 runs; R vs Burst-HADS cost -5.39 to -4.96%",
    "R5": "the branch still fires after the fix: 1,453 tier-3 burstables in 2,400 runs, against 1,477 before",
}


def tex(s):
    """Escape the handful of TeX-special characters our sources contain."""
    for a, b in (("\\", r"\textbackslash "), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"),
                 ("#", r"\#"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}"),
                 ("—", "---"), ("–", "--"), ("≤", r"$\leq$"), ("≥", r"$\geq$"),
                 ("→", r"$\rightarrow$"), ("×", r"$\times$"), ("§", r"\S"),
                 ("−", "-"), ("’", "'"), ("“", "``"), ("”", "''")):
        s = s.replace(a, b)
    return s


def register_rows():
    """(id, deviation, status) for every row of the register, in file order."""
    text = (ROOT / "DEVIATIONS.md").read_text(encoding="utf-8")
    section, out = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        m = re.match(r"^\| ([A-Z]\d+) \| ([^|]+) \|", line)
        if m and section:
            status = line.rstrip().rstrip("|").rsplit("|", 1)[-1].strip()
            out.append((section, m.group(1), m.group(2).strip(), status))
    return out


def status_short(s):
    """The status word plus its qualifier, without the evidence prose."""
    s = re.split(r"[:;(]", s, maxsplit=1)[0].strip()
    return s if len(s) <= 46 else s[:43].rstrip() + "..."


def write_register(w):
    rows = register_rows()
    counts = {}
    for _, _, _, st in rows:
        k = re.split(r"[\s—(-]", st, maxsplit=1)[0].lower()
        counts[k] = counts.get(k, 0) + 1
    order = ["corrected", "design", "open", "kept", "inert"]
    summary = ", ".join(f"{counts.get(k, 0)} {k}" for k in order if counts.get(k))
    w(r"\section{Appendix: deviation register}")
    w(r"\label{sec:deviations}")
    w("")
    w(f"Every place our re-implementations differ from the published algorithms, with the status of each. "
      f"The register holds {len(rows)} rows: {summary}. \"Corrected\" means the code now follows the source and the "
      r"row is kept because earlier results used the deviation; ``design'' is a deliberate modelling choice this "
      r"study keeps; ``open'' means the code still differs. The full register, with the measured effect and the "
      r"evidence file behind every row, ships as supplementary material (\texttt{DEVIATIONS.md}); the three rows "
      r"that bear on how the results should be read are discussed in Section~\ref{sec:validation}.")
    w("")
    w(r"\begin{table*}[t]")
    w(r"\caption{The deviation register. The effect column is filled only where the effect has been measured; "
      r"an em dash means it has not. The full text of every row, with its evidence file, is supplementary.}")
    w(r"\label{tab:deviations}")
    w(r"\centering")
    w(r"\scriptsize")
    w(r"\begin{tabular}{@{}lp{3.4cm}p{2.5cm}p{8.6cm}@{}}")
    w(r"\toprule")
    w(r"\# & Deviation & Status & Measured effect \\")
    current = None
    for section, ident, name, status in rows:
        if section != current:
            w(r"\midrule")
            w(r"\multicolumn{4}{@{}l}{\textbf{" + tex(section) + r"}} \\")
            w(r"\midrule")
            current = section
        effect = tex(EFFECTS[ident]) if ident in EFFECTS else "---"
        w(f"{ident} & {tex(name)} & {tex(status_short(status))} & {effect} " + r"\\")
    w(r"\bottomrule")
    w(r"\end{tabular}")
    w(r"\end{table*}")
    w("")


def write_cells(w, rel, label, ident, setting):
    d = rp.load_jsonl(rel)
    cells = rp.cells_of(d)
    stats = {c: rp.cell_stats(s) for c, s in cells.items()}
    w(r"\begin{longtable}{@{}lrr" + "rr" * 3 + r"@{}}")
    w(r"\caption{Per-cell means with 95\% confidence intervals, " + setting +
      r". Makespan in seconds, cost in dollars; each cell is 30 seeds. A cell in which a scheduler was infeasible "
      r"in some seed is averaged over its feasible seeds and excluded from the cross-scheduler tables "
      r"(Section~\ref{sec:results}).}\label{" + label + r"}\\")
    w(r"\toprule")
    head = (r"Scenario & $|T|$ & DF & \multicolumn{2}{c}{HADS} & \multicolumn{2}{c}{Burst-HADS} & "
            r"\multicolumn{2}{c}{R-BurstHADS} \\")
    sub = r" & & & mkp & cost & mkp & cost & mkp & cost \\"
    w(head)
    w(sub)
    w(r"\midrule")
    w(r"\endfirsthead")
    w(r"\toprule")
    w(head)
    w(sub)
    w(r"\midrule")
    w(r"\endhead")
    w(r"\bottomrule")
    w(r"\endfoot")
    for c in sorted(cells):
        st = stats[c]
        vals = []
        for k in rp.KEYS:
            mk, mkh, _ = st[k]["mk"]
            co, coh, _ = st[k]["cost"]
            vals += [f"{mk:,.0f}\\,$\\pm${mkh:,.0f}", f"{co:.3f}\\,$\\pm${coh:.3f}"]
        w(f"{c[0]} & {c[1]} & {c[2]} & " + " & ".join(vals) + r" \\")
    w(r"\end{longtable}")
    w("")


def main():
    lines = []
    w = lines.append
    w(r"% Generated by experiments/make_paper_tables.py -- do not edit by hand.")
    w(r"% Sources: DEVIATIONS.md and the committed sweeps of freeze-fix21 (" + FP + ").")
    w("")
    write_register(w)
    # longtable cannot break inside a two-column body, so the per-cell appendix
    # runs single column and \twocolumn restores the document at the end.
    w(r"\onecolumn")
    w(r"\section{Appendix: per-cell results}")
    w(r"\label{sec:percell}")
    w("")
    w(r"These are the cell means behind every aggregate in Section~\ref{sec:results}: "
      r"Table~\ref{tab:cells-on} under the reference account limits and Table~\ref{tab:cells-off} without them.")
    w("")
    write_cells(w, f"experiments/sweep_raw_{FP}.jsonl", "tab:cells-on", "T3", "launch limits on")
    write_cells(w, f"experiments/sweep_variant_nocap_{FP}.jsonl", "tab:cells-off", "T4", "launch limits off")
    w(r"\twocolumn")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
