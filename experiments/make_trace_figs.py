"""
Runtime-behaviour figures built from experiments/trace_out/trace_*.json.

Produces, into ./trace_fig/ :
  trace_gantt_<sched>.png   one row per VM, bands coloured by state
  trace_fleet.png           how many VMs are busy / idle / hibernated over time
  trace_credits.png         CPU-credit balance of every burstable VM
  trace_spend.png           cumulative billed VM-seconds split by market
"""

import json, os, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "trace_out")
OUT = os.path.join(HERE, "trace_fig")
os.makedirs(OUT, exist_ok=True)

SCHEDS = [("hads", "HADS"), ("burst", "Burst-HADS"), ("rburst", "R-BurstHADS")]

C_BUSY = "#1baf7a"
C_WAIT = "#a9e3cb"
C_IDLE = "#c3c8d0"
C_HIB = "#e34948"
C_TERM = "#7a8290"
SURF = "#ffffff"
INK = "#1c1f24"
GRID = "#e3e6eb"

MARKET_ORDER = {"spot": 0, "burstable": 1, "ondemand": 2}


def load(key):
    with open(os.path.join(SRC, f"trace_{key}.json")) as f:
        return json.load(f)


def vm_rows(tr):
    """Stable row ordering: spot, then burstable, then on-demand; id within."""
    seen = {}
    for snap in tr["snapshots"]:
        for v in snap["vms"]:
            seen[v["id"]] = (v["type"], v["mkt"])
    rows = sorted(seen.items(), key=lambda kv: (MARKET_ORDER[kv[1][1]], kv[0]))
    return [(vid, t, m) for vid, (t, m) in rows]


def bands(tr, vid):
    """Piecewise-constant occupancy bands for one VM: [(t0, t1, kind, run, wait)].

    NOTE: vm.state is only refreshed when a task completes, so it reads
    'idle' for a VM that is in fact executing.  len(vm.running) and
    len(vm.tasks) -- carried in the trace as 'run' and 'q' -- are the
    fields the rest of the simulator treats as ground truth, so
    occupancy is derived from those.  state is consulted only for the
    two conditions it does track reliably: hibernated and terminated.
    """
    pts = []
    for snap in tr["snapshots"]:
        rec = None
        for v in snap["vms"]:
            if v["id"] == vid:
                rec = v
                break
        if rec is None:
            pts.append((snap["t"], None, 0, 0))
            continue
        if rec["state"] == "hibernated":
            kind = "hib"
        elif rec["state"] == "terminated":
            kind = "term"
        elif rec["run"] > 0:
            kind = "busy"
        elif rec["q"] > 0:
            kind = "wait"
        else:
            kind = "idle"
        pts.append((snap["t"], kind, rec["run"], max(0, rec["q"] - rec["run"])))
    out = []
    for i in range(len(pts) - 1):
        t0, k0, r0, w0 = pts[i]
        t1 = pts[i + 1][0]
        if k0 is None or t1 <= t0:
            continue
        if out and out[-1][2] == k0 and out[-1][3] == r0 and out[-1][4] == w0 \
                and abs(out[-1][1] - t0) < 1e-9:
            out[-1] = (out[-1][0], t1, k0, r0, w0)
        else:
            out.append((t0, t1, k0, r0, w0))
    return out


def draw_gantt(key, label):
    tr = load(key)
    mk = tr["summary"]["makespan"]
    xmax = mk * 1.06
    rows = vm_rows(tr)
    hib_ts = sorted({e["t"] for e in tr["events"] if e["kind"] == "HIBERNATE"})
    prov_ts = {e["vm"]: e["t"] for e in tr["events"] if e["kind"] == "PROVISION"}

    h = 1.0 + 0.32 * len(rows)
    fig, ax = plt.subplots(figsize=(11.0, h))
    fig.patch.set_facecolor(SURF)
    ax.set_facecolor(SURF)

    for t in hib_ts:
        if t <= xmax:
            ax.axvline(t, color="#9aa2ad", lw=0.7, ls=(0, (3, 3)), zorder=0)

    yt, yl = [], []
    for i, (vid, vtype, mkt) in enumerate(rows):
        y = len(rows) - 1 - i
        yt.append(y)
        tag = {"spot": "spot", "burstable": "burstable", "ondemand": "on-demand"}[mkt]
        yl.append(f"{vtype}#{vid}  ({tag})")
        if mkt == "burstable":
            ax.axhspan(y - 0.45, y + 0.45, color="#fff6e0", zorder=0)
        for t0, t1, kind, run, wait in bands(tr, vid):
            if t0 >= xmax:
                continue
            t1 = min(t1, xmax)
            w = t1 - t0
            if kind == "hib":
                ax.barh(y, w, left=t0, height=0.62, color=C_HIB,
                        edgecolor="#8f1f1f", linewidth=0.5, hatch="////", zorder=3)
                continue
            if kind == "term":
                ax.barh(y, w, left=t0, height=0.07, color=C_TERM,
                        edgecolor="none", zorder=2)
                continue
            ax.barh(y, w, left=t0, height=0.06, color=C_IDLE,
                    edgecolor="none", zorder=2)
            if run > 0:
                ax.barh(y + 0.16, w, left=t0, height=0.27, color=C_BUSY,
                        edgecolor="none", zorder=4)
                if w > xmax * 0.045:
                    ax.text(t0 + w / 2, y + 0.16, str(run), ha="center",
                            va="center", fontsize=6.2, color="white", zorder=5)
            if wait > 0:
                ax.barh(y - 0.16, w, left=t0, height=0.27, color=C_WAIT,
                        edgecolor="none", zorder=4)
                if w > xmax * 0.045:
                    ax.text(t0 + w / 2, y - 0.16, str(wait), ha="center",
                            va="center", fontsize=6.2, color="#20563f", zorder=5)

    for vmname, t in prov_ts.items():
        try:
            vid = int(vmname.split("#")[1])
        except Exception:
            continue
        for i, (rid, _, _) in enumerate(rows):
            if rid == vid and t <= xmax:
                ax.plot([t], [len(rows) - 1 - i], marker="v", ms=7,
                        color="#2a78d6", zorder=5, clip_on=False)

    ax.set_yticks(yt)
    ax.set_yticklabels(yl, fontsize=8, color=INK)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlim(0, xmax)
    ax.set_xlabel("simulation time (s)", fontsize=9, color=INK)
    ax.set_title(f"{label} — what every VM is doing, second by second\n"
                 f"makespan {mk:.1f}s, cost ${tr['summary']['total_cost']:.4f}, "
                 f"deadline {tr['deadline']:.0f}s, n={tr['n']} tasks",
                 fontsize=10.5, color=INK, loc="left")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors="#5b636e", labelsize=8)

    handles = [
        Patch(facecolor=C_BUSY, label="upper lane: tasks executing (count inside)"),
        Patch(facecolor=C_WAIT, label="lower lane: tasks queued, waiting"),
        Patch(facecolor=C_HIB, hatch="////", edgecolor="#8f1f1f",
              label="hibernated (revoked)"),
        Patch(facecolor=C_IDLE, label="alive, holding nothing"),
        Patch(facecolor=C_TERM, label="terminated"),
        Line2D([], [], color="#9aa2ad", ls=(0, (3, 3)), label="hibernation instant"),
        Line2D([], [], color="#2a78d6", marker="v", ls="none",
               label="new VM finishes booting"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.14 - 0.9 / h),
              ncol=4, frameon=False, fontsize=8)
    fig.tight_layout()
    p = os.path.join(OUT, f"trace_gantt_{key}.png")
    fig.savefig(p, dpi=190, bbox_inches="tight", facecolor=SURF)
    plt.close(fig)
    return p


def draw_fleet():
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 7.4), sharex=True, sharey=True)
    fig.patch.set_facecolor(SURF)
    for ax, (key, label) in zip(axes, SCHEDS):
        tr = load(key)
        mk = tr["summary"]["makespan"]
        ts, busy, idle, hib = [], [], [], []
        for snap in tr["snapshots"]:
            if snap["t"] > mk * 1.06:
                continue
            ts.append(snap["t"])
            b = i_ = h = 0
            for v in snap["vms"]:
                if v["state"] == "hibernated":
                    h += 1
                elif v["state"] == "terminated":
                    pass
                elif v["run"] > 0:
                    b += 1
                else:
                    i_ += 1
            busy.append(b); idle.append(i_); hib.append(h)
        ax.set_facecolor(SURF)
        ax.stackplot(ts, hib, busy, idle,
                     colors=[C_HIB, C_BUSY, C_IDLE], step="post",
                     labels=["hibernated", "executing", "alive but empty"])
        ax.plot(ts, hib, drawstyle="steps-post", color="#8f1f1f", lw=1.2)
        ax.set_ylabel("VMs", fontsize=9, color=INK)
        ax.set_title(f"{label}   ({len(set(v['id'] for s in tr['snapshots'] for v in s['vms']))}"
                     f" machines ever created)", fontsize=10, color=INK, loc="left")
        ax.grid(color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#5b636e", labelsize=8)
    axes[-1].set_xlabel("simulation time (s)", fontsize=9, color=INK)
    axes[0].legend(loc="upper right", frameon=False, fontsize=8, ncol=3)
    fig.suptitle("Fleet composition over time — the red band at the bottom is how many "
                 "machines are frozen", fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    p = os.path.join(OUT, "trace_fleet.png")
    fig.savefig(p, dpi=190, facecolor=SURF)
    plt.close(fig)
    return p


def draw_credits():
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.5), sharey=True)
    fig.patch.set_facecolor(SURF)
    styles = ["-", "--", "-.", ":"]
    for ax, (key, label) in zip(axes, SCHEDS):
        tr = load(key)
        mk = tr["summary"]["makespan"]
        ser = {}
        for snap in tr["snapshots"]:
            if snap["t"] > mk * 1.06:
                continue
            for v in snap["vms"]:
                if v["cr"] is not None:
                    ser.setdefault((v["id"], v["type"]), []).append((snap["t"], v["cr"]))
        ax.set_facecolor(SURF)
        ax.axhline(144, color="#9aa2ad", lw=0.8, ls=(0, (4, 3)))
        ax.text(2, 144.25, "cap 144", fontsize=7, color="#5b636e")
        for k, ((vid, vtype), pts) in enumerate(sorted(ser.items())):
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            ax.plot(xs, ys, drawstyle="steps-post", lw=1.5,
                    ls=styles[k % len(styles)], label=f"{vtype}#{vid}")
        ax.set_title(label, fontsize=10, color=INK, loc="left")
        ax.set_xlabel("time (s)", fontsize=9, color=INK)
        ax.grid(color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#5b636e", labelsize=8)
        ax.legend(frameon=False, fontsize=7, loc="lower left")
    axes[0].set_ylabel("CPU-credit balance", fontsize=9, color=INK)
    axes[0].set_ylim(137, 145.6)
    fig.suptitle("Burstable CPU credits — every drop is one rescued task run at full "
                 "speed in burst mode", fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    p = os.path.join(OUT, "trace_credits.png")
    fig.savefig(p, dpi=190, facecolor=SURF)
    plt.close(fig)
    return p


RATE = {("c5.large", "spot"): 0.0306, ("c5.xlarge", "spot"): 0.0612,
        ("m5.xlarge", "spot"): 0.0700, ("t3.large", "burstable"): 0.0832,
        ("c5.large", "ondemand"): 0.0850}


def draw_spend():
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.7), sharey=True)
    fig.patch.set_facecolor(SURF)
    cols = {"spot": "#2a78d6", "burstable": "#e8a020", "ondemand": "#8a3ffc"}
    lss = {"spot": "-", "burstable": "--", "ondemand": "-."}
    for ax, (key, label) in zip(axes, SCHEDS):
        tr = load(key)
        mk = tr["summary"]["makespan"]
        ts = []
        acc = {"spot": [], "burstable": [], "ondemand": []}
        for snap in tr["snapshots"]:
            ts.append(snap["t"])
            tot = {"spot": 0.0, "burstable": 0.0, "ondemand": 0.0}
            for v in snap["vms"]:
                tot[v["mkt"]] += v["bill"] * RATE[(v["type"], v["mkt"])] / 3600.0
            for m in acc:
                acc[m].append(tot[m])
        ax.set_facecolor(SURF)
        ax.axvline(mk, color="#3b424c", lw=1.0, ls=(0, (4, 3)))
        ax.annotate("last task finishes", xy=(mk, 0.97),
                    xycoords=("data", "axes fraction"), xytext=(4, 0),
                    textcoords="offset points", fontsize=7.5,
                    color="#3b424c", ha="left", va="top")
        for m in ("spot", "burstable", "ondemand"):
            ax.plot(ts, acc[m], color=cols[m], ls=lss[m], lw=1.7,
                    label={"ondemand": "on-demand"}.get(m, m))
        ax.set_title(label, fontsize=10, color=INK, loc="left")
        ax.set_xlabel("time (s)", fontsize=9, color=INK)
        ax.grid(color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors="#5b636e", labelsize=8)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    axes[0].set_ylabel("accumulated cost (USD)", fontsize=9, color=INK)
    fig.suptitle("Where the money goes — and how much of it is spent after the "
                 "work is already done", fontsize=10.5, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.91])
    p = os.path.join(OUT, "trace_spend.png")
    fig.savefig(p, dpi=190, facecolor=SURF)
    plt.close(fig)
    return p


if __name__ == "__main__":
    for k, l in SCHEDS:
        print(draw_gantt(k, l))
    print(draw_fleet())
    print(draw_credits())
    print(draw_spend())
