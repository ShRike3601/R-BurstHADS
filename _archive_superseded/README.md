# Superseded material

Nothing in this folder is current. Every number in every file here predates the
frozen simulator `freeze-fix21` (fingerprint `2439a00d7f74`) and therefore
predates most of the twenty-one fidelity fixes. Several of these files state
results that are now known to be wrong, so they must not be quoted, sent to
anyone, or used as a source for the paper. They are kept only as a record of
how the work developed, and they can be deleted once the paper is submitted.

The live paper is `paper/paper.tex`, its generated tables are
`paper/tables_generated.tex`, its six figures are in `paper/fig/`, and the
bundle for Overleaf is `paper/RBurstHADS_overleaf.zip`. The current results are
in `RESULTS_PACK.md` and the current deviation register is `DEVIATIONS.md`.

## paper_drafts

`paper_2026-08-28.pdf` is the first compiled draft, from before the deadline
sweep and before the per-core speed fix. `paper_2026-08-28_rootcopy_identical.pdf`
was a byte-identical duplicate that sat in the project root.

`paper_v2.tex`, `paper_v2.pdf` and `paper_v2_placeholder.pdf` are the 14
September iteration. This is the version most likely to have been circulated to
a reader, and it is the one that shows only two algorithms and reports the old
headline figures. If anyone is reading a copy of the paper that does not
contain seven algorithms and a provenance table, they are reading this file.

`paper.tex.before_algorithm_provenance_edit` is the immediate predecessor of the
current paper, kept only until the next compile confirms the edit is sound.

## reports_2026-09-08

Three deliverables written on 8 September: `changes_report`, a summary of the
fixes made up to that date; `rbursthads_technical`, a description of how the
scheduler works; and `runtime_behaviour_report`, a second-by-second trace of a
scheduling run. Each exists as both .docx and .pdf. The mechanisms they
describe are broadly still accurate, but every figure they quote is stale, and
the technical report describes the burstable tier as a latency hedge, which
measurement later showed it is not.

## figures_old

`fig_trace` holds the figures for the runtime behaviour report. `figures_v2`
holds the original multi-panel figures, ten graphs to a file, which the
single-column figure rule replaced. `fig_fix20` and `fig_fix21` hold
intermediate figure sets generated while the fixes were still being measured;
both were superseded when the figure set changed to the six absolute-value
charts now in `paper/fig/`.
