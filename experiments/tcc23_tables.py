"""
TCC23's Tables 7 and 9, transcribed (Teylo et al., IEEE TCC 11(1), 2023).

Table 9 has no text layer: the PDF draws it as glyph outlines, so text
extraction returns only its caption. It was transcribed from a raster of
page 11's vector paths (scratchpad raster_page.py, 6x). `check()` verifies
the transcription three ways: every printed "Diff" percentage against the
one recomputed from the printed costs and makespans (costs are printed to
$0.001, so a few tenths of a point of rounding is expected), and the four
aggregates the section 4 text states, which must come out exactly.

Conventions, as printed:
  Diff HADS (%)     = (HADS - Burst-HADS) / HADS; positive = Burst-HADS lower
  Diff AutoBoT (%)  = (AutoBoT - Burst-HADS) / AutoBoT
  hib, res          = average number of hibernations and of resumes per run
                      (one column per job and scenario, not per framework)
  od_*              = "# used regular on-demand VMs" per framework
Each cell is the average of three executions.

Usage: python experiments\\tcc23_tables.py   (runs check())
"""

JOBS = ["J60", "J80", "J100", "ED200"]
SCENARIOS = ["sc1", "sc2", "sc3", "sc4", "sc5"]

# Table 7, no hibernation: (cost $, makespan s)
T7 = {
    "J60":   dict(burst=(0.112, 1274), hads=(0.067, 2290), autobot=(0.166, 2221), ondemand=(0.271, 1112)),
    "J80":   dict(burst=(0.151, 1329), hads=(0.104, 2295), autobot=(0.199, 2266), ondemand=(0.312, 1190)),
    "J100":  dict(burst=(0.176, 1660), hads=(0.112, 2332), autobot=(0.218, 2342), ondemand=(0.371, 1462)),
    "ED200": dict(burst=(0.357, 2275), hads=(0.267, 2580), autobot=(0.387, 2566), ondemand=(0.698, 1887)),
}

_COLS = ("hib", "res", "od_burst", "od_hads", "od_autobot",
         "burst_cost", "burst_mk", "hads_cost", "hads_mk", "autobot_cost", "autobot_mk",
         "diff_hads_cost", "diff_hads_mk", "diff_autobot_cost", "diff_autobot_mk")

_ROWS = {
    ("J60", "sc1"):   (0.66, 0.00, 0.00, 0.00, 1, 0.119, 1274, 0.091, 2620, 0.166, 2221, -30.77, 51.37, 28.31, 42.64),
    ("J60", "sc2"):   (3.33, 0.00, 1.33, 2.33, 1, 0.204, 1277, 0.257, 2549, 0.173, 2228,  20.54, 49.90, -17.92, 42.68),
    ("J60", "sc3"):   (2.33, 2.33, 1.33, 0.00, 1, 0.127, 1752, 0.101, 2539, 0.178, 2237, -26.07, 31.00, 28.46, 21.68),
    ("J60", "sc4"):   (5.33, 4.00, 1.67, 0.00, 1, 0.142, 1857, 0.119, 2634, 0.180, 2252, -19.90, 29.50, 21.07, 17.54),
    ("J60", "sc5"):   (2.66, 1.00, 1.33, 2.00, 1, 0.150, 1445, 0.169, 2359, 0.170, 2236,  11.44, 38.75, 11.96, 35.38),
    ("J80", "sc1"):   (1.00, 0.00, 1.33, 0.33, 2, 0.167, 1419, 0.150, 2581, 0.206, 2273, -11.33, 45.03, 18.93, 37.57),
    ("J80", "sc2"):   (5.00, 0.00, 1.00, 3.00, 2, 0.210, 2267, 0.298, 2591, 0.211, 2278,  29.48, 12.50,  0.47,  0.48),
    ("J80", "sc3"):   (3.00, 1.00, 1.67, 1.00, 2, 0.164, 1367, 0.147, 2602, 0.214, 2276, -11.34, 47.46, 23.52, 39.94),
    ("J80", "sc4"):   (9.66, 7.66, 1.00, 2.00, 3, 0.244, 2488, 0.212, 2607, 0.301, 2460, -15.25,  4.56, 18.83, -1.14),
    ("J80", "sc5"):   (3.00, 1.00, 1.33, 3.00, 2, 0.195, 1589, 0.246, 2529, 0.228, 2266,  20.47, 37.17, 14.25, 29.88),
    ("J100", "sc1"):  (2.00, 0.00, 0.00, 0.00, 2, 0.191, 1798, 0.157, 2332, 0.226, 2350, -21.76, 22.90, 15.49, 23.49),
    ("J100", "sc2"):  (7.00, 0.00, 1.33, 3.00, 2, 0.212, 1900, 0.353, 2518, 0.222, 2342,  39.94, 24.54,  4.50, 18.87),
    ("J100", "sc3"):  (6.00, 3.00, 1.67, 1.00, 2, 0.201, 1925, 0.166, 2636, 0.224, 2360, -21.08, 26.97, 10.27, 18.43),
    ("J100", "sc4"):  (11.00, 9.00, 1.00, 0.00, 3, 0.286, 2453, 0.278, 2591, 0.312, 2677, -2.88,  5.33,  8.33,  8.37),
    ("J100", "sc5"):  (3.66, 2.00, 1.00, 2.50, 2, 0.166, 1547, 0.189, 2543, 0.227, 2366,  12.49, 39.15, 26.98, 34.62),
    ("ED200", "sc1"): (3.00, 0.00, 1.00, 0.33, 3, 0.388, 2327, 0.314, 2680, 0.414, 2630, -23.57, 13.17,  6.28, 11.52),
    ("ED200", "sc2"): (8.00, 0.00, 2.00, 5.00, 3, 0.482, 2448, 0.512, 2676, 0.430, 2661,   5.86,  8.52, -12.09, 8.00),
    ("ED200", "sc3"): (6.66, 4.00, 2.33, 1.00, 3, 0.427, 2345, 0.387, 2672, 0.457, 2675, -10.34, 12.24,  6.56, 12.34),
    ("ED200", "sc4"): (9.00, 6.00, 2.00, 1.00, 3, 0.411, 2560, 0.389, 2690, 0.447, 2667,  -5.66,  4.83,  8.05,  4.01),
    ("ED200", "sc5"): (4.33, 2.33, 1.67, 3.00, 3, 0.367, 2342, 0.467, 2674, 0.411, 2765,  21.41, 12.42, 10.71, 15.30),
}

T9 = {k: dict(zip(_COLS, v)) for k, v in _ROWS.items()}

# Section 4 text
T9_TEXT = dict(avg_mk_reduction=25.87, j60_mk_reduction=40.10, ed200_mk_reduction=10.24,
               avg_cost_increase=1.92)


def burst_cost_change_vs_hads(job, sc):
    """Burst-HADS cost change vs HADS, %, from the printed Diff (sign flipped)."""
    return -T9[(job, sc)]["diff_hads_cost"]


def check(verbose=True):
    worst = {}
    for (j, sc), r in T9.items():
        for col, a, b in (("diff_hads_cost", "hads_cost", "burst_cost"),
                          ("diff_hads_mk", "hads_mk", "burst_mk"),
                          ("diff_autobot_cost", "autobot_cost", "burst_cost"),
                          ("diff_autobot_mk", "autobot_mk", "burst_mk")):
            recomputed = 100.0 * (r[a] - r[b]) / r[a]
            dev = abs(recomputed - r[col])
            if dev > worst.get(col, (0.0, None))[0]:
                worst[col] = (dev, (j, sc, recomputed, r[col]))
    n = len(T9)
    agg = dict(
        avg_mk_reduction=sum(r["diff_hads_mk"] for r in T9.values()) / n,
        j60_mk_reduction=sum(T9[("J60", s)]["diff_hads_mk"] for s in SCENARIOS) / 5,
        ed200_mk_reduction=sum(T9[("ED200", s)]["diff_hads_mk"] for s in SCENARIOS) / 5,
        avg_cost_increase=-sum(r["diff_hads_cost"] for r in T9.values()) / n,
    )
    ok = all(abs(round(agg[k], 2) - T9_TEXT[k]) < 0.006 for k in T9_TEXT)
    if verbose:
        for col, (dev, where) in worst.items():
            print(f"  {col:18s} largest |printed - recomputed| = {dev:.2f} pt at {where[0]} {where[1]}"
                  f" (recomputed {where[2]:+.2f}, printed {where[3]:+.2f})")
        for k in T9_TEXT:
            print(f"  {k:20s} from the transcribed cells {agg[k]:+.3f}   text {T9_TEXT[k]:+.2f}")
        print("  aggregates reproduce the text:", ok)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
