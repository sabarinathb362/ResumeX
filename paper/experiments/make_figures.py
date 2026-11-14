"""
Figures for the ResumeX paper. Reads results.json (written by run_experiments.py) and writes PDFs to
paper/figures/. Works locally or in Google Colab: upload results.json next to this script and run it.

    python paper/experiments/make_figures.py
"""
import collections
import json
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RES = json.loads((HERE / "results.json").read_text())
OUT = HERE.parent / "figures"
OUT.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5, "legend.fontsize": 7.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5, "savefig.bbox": "tight", "savefig.dpi": 300,
})
C = {"a": "#2f5d50", "b": "#7aa37a", "c": "#d9a441", "d": "#b5523b", "grey": "#8a8a8a", "blue": "#3a6ea5"}
R = RES["resumes"]


def save(fig, name):
    fig.savefig(OUT / f"{name}.pdf")
    fig.savefig(OUT / f"{name}.png")
    plt.close(fig)


# Fig. 2 — ATS vs. RRI per resume, and mean normalised score per rubric dimension
def fig_scores():
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.5), gridspec_kw={"width_ratios": [1, 1.25, 1.25]})
    ax = axes[0]
    ats = np.array([r["ats"] for r in R]); rri = np.array([r["rri"] for r in R])
    ax.scatter(ats, rri, s=22, color=C["a"], edgecolor="white", linewidth=0.6, zorder=3)
    ax.plot([0, 100], [0, 100], ls="--", lw=0.7, color=C["grey"])
    ax.set_xlim(35, 102); ax.set_ylim(35, 102)
    ax.set_xlabel("ATS compatibility (0-100)"); ax.set_ylabel("Recruiter Readability Index (0-100)")
    r = np.corrcoef(ats, rri)[0, 1]
    ax.set_title(f"(a) ATS vs. RRI, n={len(R)}, r={r:.2f}")
    for ax, key, title in ((axes[1], "ats_dims", "(b) ATS dimensions"), (axes[2], "rri_dims", "(c) RRI dimensions")):
        d = collections.defaultdict(list)
        for x in R:
            for k, v in x[key].items():
                d[k].append(v)
        names = list(d)
        m = [st.mean(d[k]) for k in names]
        sd = [st.pstdev(d[k]) for k in names]
        y = np.arange(len(names))[::-1]
        err = [[min(sd[i], m[i]) for i in range(len(m))], [min(sd[i], 1 - m[i]) for i in range(len(m))]]
        ax.barh(y, m, xerr=err, color=C["b"] if key == "ats_dims" else C["c"], height=0.62,
                error_kw={"lw": 0.6, "capsize": 1.5, "ecolor": "#555"})
        ax.set_yticks(y); ax.set_yticklabels([n.replace(" & ", " & ") for n in names])
        ax.set_xlim(0, 1.08); ax.set_xlabel("Mean share of points earned"); ax.set_title(title)
        ax.grid(axis="y", visible=False)
    fig.tight_layout(w_pad=0.6)
    save(fig, "fig_scores")


# Fig. 3 — bullet grades by section and the four bullet properties
def fig_bullets():
    b = RES["bullets"]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.3), gridspec_kw={"width_ratios": [1.4, 1]})
    ax = axes[0]
    order = [s for s in ["experience", "projects", "volunteer", "extracurricular", "leadership"] if s in b["by_section"]]
    left = np.zeros(len(order))
    for g, col in zip("ABCD", (C["a"], C["b"], C["c"], C["d"])):
        vals = np.array([b["by_section"][s].get(g, 0) for s in order])
        ax.barh(order[::-1], vals[::-1], left=left[::-1], color=col, label=f"Grade {g}", height=0.6)
        left += vals
    ax.set_xlabel("Number of bullets"); ax.set_title(f"(a) Bullet grades by section (n={b['n']})")
    ax.legend(ncol=2, loc="lower right", bbox_to_anchor=(1.0, 0.06), frameon=False); ax.grid(axis="y", visible=False)
    ax = axes[1]
    names = ["action", "specific", "outcome", "metric"]
    share = [b["flags"][k] / b["n"] for k in names]
    ax.bar(["Action verb", "Specific", "Outcome", "Metric"], share, color=[C["a"], C["b"], C["c"], C["d"]], width=0.6)
    for i, s in enumerate(share):
        ax.text(i, s + 0.02, f"{s:.0%}", ha="center", fontsize=7.5)
    ax.set_ylim(0, 1.05); ax.set_ylabel("Share of bullets"); ax.set_title("(b) Bullet properties detected")
    fig.tight_layout(w_pad=1.0)
    save(fig, "fig_bullets")


# Fig. 4 — embedding fine-tuning: training loss and Spearman correlation before/after
LOG = [(0.1256, 4.5741), (0.2513, 4.2834), (0.3769, 4.1436), (0.5025, 3.9098), (0.6281, 3.9975), (0.7538, 3.9482),
       (0.8794, 3.8354), (1.0050, 3.8265), (1.1307, 3.7760), (1.2563, 3.7500), (1.3819, 3.6104), (1.5075, 3.6712),
       (1.6332, 3.5690), (1.7588, 3.6018), (1.8844, 3.5995)]          # from the model card training log
VAL = [(1.0, 2.5161, 0.5193), (2.0, 2.4958, 0.5493)]                   # epoch, val loss, val Spearman
TEST = {"bge-small-en-v1.5 (base)": 0.3687, "bge-small-resumex (ours)": 0.6948}


def fig_embedding():
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.2), gridspec_kw={"width_ratios": [1.5, 1]})
    ax = axes[0]
    e, l = zip(*LOG)
    ax.plot(e, l, color=C["a"], lw=1.2, marker="o", ms=2.5, label="Training loss (CoSENT)")
    ax.plot([v[0] for v in VAL], [v[1] for v in VAL], color=C["d"], lw=1.2, marker="s", ms=3.5, label="Validation loss")
    ax.set_xlabel("Epoch"); ax.set_ylabel("Loss"); ax.set_title("(a) Fine-tuning on 6,363 resume-JD pairs")
    ax.legend(frameon=False)
    ax2 = ax.twinx()
    ax2.plot([v[0] for v in VAL], [v[2] for v in VAL], color=C["blue"], ls="--", marker="^", ms=3.5)
    ax2.set_ylabel("Validation Spearman", color=C["blue"]); ax2.set_ylim(0.3, 0.75); ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    ax = axes[1]
    ks = list(TEST)
    ax.bar(["Base", "Fine-tuned"], [TEST[k] for k in ks], color=[C["grey"], C["a"]], width=0.55)
    for i, k in enumerate(ks):
        ax.text(i, TEST[k] + 0.015, f"{TEST[k]:.3f}", ha="center")
    ax.set_ylim(0, 0.8); ax.set_ylabel("Spearman (test)"); ax.set_title("(b) Held-out fit correlation")
    fig.tight_layout(w_pad=1.0)
    save(fig, "fig_embedding")


# Fig. 5 — in-place editing: outcome vs. length of the replacement text
def fig_inplace():
    d = RES["inplace"]["by_ratio"]
    ratios = sorted(d, key=float)
    tot = np.array([sum(d[r].get(k, 0) for k in ("ok", "fail")) for r in ratios], dtype=float)
    scaled = np.array([d[r].get("scaled", 0) for r in ratios]) / tot
    ok = np.array([d[r].get("ok", 0) for r in ratios]) / tot - scaled
    fail = np.array([d[r].get("fail", 0) for r in ratios]) / tot
    x = np.arange(len(ratios))
    fig, ax = plt.subplots(figsize=(5.6, 2.2))
    ax.bar(x, ok, color=C["a"], label="Placed at original size", width=0.62)
    ax.bar(x, scaled, bottom=ok, color=C["c"], label="Placed, condensed (>= 88%)", width=0.62)
    ax.bar(x, fail, bottom=ok + scaled, color=C["d"], label="Rejected (layout kept)", width=0.62)
    ax.set_xticks(x); ax.set_xticklabels([f"{float(r):.1f}x" for r in ratios])
    ax.set_xlabel("Replacement length / original length (words)"); ax.set_ylabel("Share of edits")
    ax.set_ylim(0, 1); ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    ax.set_title(f"In-place edits on {RES['n_resumes']} PDFs ({int(tot[0])} text runs per ratio)")
    fig.tight_layout()
    save(fig, "fig_inplace")


# Fig. 6 — per-stage latency of the deterministic pipeline (CPU)
def fig_latency():
    d = collections.defaultdict(list)
    for x in R:
        for k, v in x["latency_ms"].items():
            d[k].append(v)
    label = {"parse": "Layout parsing", "ats": "ATS rules", "rri": "RRI grading", "insights": "Insight merge",
             "skim": "Skim simulation", "viq": "Impact quotient", "parser_sim": "Naive-parser views",
             "stealth": "Hidden-text scan", "timeline": "Timeline check"}
    keys = sorted(d, key=lambda k: st.median(d[k]))
    fig, ax = plt.subplots(figsize=(4.4, 2.3))
    y = np.arange(len(keys))
    med = [st.median(d[k]) for k in keys]
    lo = [med[i] - min(d[k]) for i, k in enumerate(keys)]
    hi = [max(d[k]) - med[i] for i, k in enumerate(keys)]
    ax.barh(y, med, xerr=[lo, hi], color=C["blue"], height=0.6, error_kw={"lw": 0.6, "capsize": 1.5})
    ax.set_xscale("log"); ax.set_yticks(y); ax.set_yticklabels([label[k] for k in keys])
    ax.set_xlabel("Milliseconds per resume (median, min-max)"); ax.grid(axis="y", visible=False)
    ax.set_title("Deterministic pipeline latency")
    fig.tight_layout()
    save(fig, "fig_latency")


if __name__ == "__main__":
    for f in (fig_scores, fig_bullets, fig_embedding, fig_inplace, fig_latency):
        f()
        print("wrote", f.__name__)
