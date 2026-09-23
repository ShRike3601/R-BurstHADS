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
    w(r"\begin{table}[t]")
    w(r"\caption{The deviation register, by section.}")
    w(r"\label{tab:deviations}")
    w(r"\centering")
    w(r"\scriptsize")
    w(r"\begin{tabular}{@{}llp{3.9cm}l@{}}")
    w(r"\toprule")
    w(r" & \# & Deviation & Status \\")
    current = None
    for section, ident, name, status in rows:
        if section != current:
            w(r"\midrule")
            w(r"\multicolumn{4}{@{}l}{\textbf{" + tex(section) + r"}} \\")
            current = section
        w(f"& {ident} & {tex(name)} & {tex(status_short(status))} " + r"\\")
    w(r"\bottomrule")
    w(r"\end{tabular}")
    w(r"\end{table}")
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
    w(r"\section{Appendix: per-cell results}")
    w(r"\label{sec:percell}")
    w("")
    w(r"These are the cell means behind every aggregate in Section~\ref{sec:results}: "
      r"Table~\ref{tab:cells-on} under the reference account limits and Table~\ref{tab:cells-off} without them.")
    w("")
    write_cells(w, f"experiments/sweep_raw_{FP}.jsonl", "tab:cells-on", "T3", "launch limits on")
    write_cells(w, f"experiments/sweep_variant_nocap_{FP}.jsonl", "tab:cells-off", "T4", "launch limits off")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
