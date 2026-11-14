"""Fig. 1 of the ResumeX paper: system architecture. Writes paper/figures/fig_architecture.pdf/.png."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).resolve().parent.parent / "figures"
OUT.mkdir(exist_ok=True)
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"], "font.size": 7.5})

fig, ax = plt.subplots(figsize=(7.4, 3.5))
ax.set_xlim(0, 100); ax.set_ylim(0, 48); ax.axis("off")

FILL = {"in": "#eef2ea", "det": "#dfe9dc", "ml": "#f6ead2", "llm": "#f3dcd5", "out": "#e3e9f2", "guard": "#ffffff"}


def box(x, y, w, h, title, lines=(), kind="det", bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=0.8",
                                fc=FILL[kind], ec="#3b3b3b", lw=0.7))
    ax.text(x + w / 2, y + h - 1.6, title, ha="center", va="top", fontweight="bold" if bold else "normal", fontsize=7.6)
    for i, l in enumerate(lines):
        ax.text(x + w / 2, y + h - 4.4 - i * 2.4, l, ha="center", va="top", fontsize=6.6)


def arrow(a, b, style="-|>", ls="-", color="#3b3b3b"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=7, lw=0.7, ls=ls, color=color,
                                 shrinkA=1, shrinkB=1))


# column 1: inputs + ingestion
box(1, 34, 16, 12, "Inputs", ["Resume: PDF, DOCX,", "LaTeX, Typst", "+ optional JD"], "in")
box(1, 13, 17, 18, "Layout-aware\ningestion", ["","PyMuPDF spans + fonts", "v2 reading order", "sections > entries", "> statements (line ids)",
                                              "JD requirement parser"], "det")
arrow((9, 34), (9, 31.4))

# column 2: deterministic analysis
box(21, 30, 22, 16, "Deterministic scoring", ["ATS rubric: 9 rules, 100 pts", "RRI: 7 dimensions, 100 pts",
                                              "bullet grades A-D", "VIQ, simulated 7.4 s skim",
                                              "naive-parser views"], "det")
box(21, 13, 22, 14.5, "Integrity checks", ["hidden-text scan (render mode,", "opacity, size, contrast)",
                                           "timeline consistency", "GitHub claim check (opt-in)"], "det")
# column 3: learned components
box(47, 30, 22, 16, "Semantic matching", ["fine-tuned bge-small-resumex", "7-dimension hybrid fit score",
                                          "alias + taxonomy matching", "requirement-level evidence"], "ml")
box(47, 13, 22, 14.5, "Hybrid RAG", ["26 chunks: role norms, skills,", "guidance, project archetypes",
                                     "0.65 dense + 0.35 BM25", "cited chunk ids"], "ml")
# column 4: LLM + guards
box(73, 30, 26, 16, "Tiered local LLM (Ollama)", ["fast: Qwen3-4B, editor co-pilot", "deep: Qwen2.5-7B, background",
                                                  "temperature 0, JSON schema", "labels only, never scores"], "llm")
box(73, 13, 26, 14.5, "Grounding guards", ["fact-checker: numbers + entities", "alias / hypernym taxonomy",
                                           "verbatim-quote check (STAR)", "rejected outputs are shown"], "guard")
# bottom: outputs
box(1, 0.5, 98, 9.5, "", [], "out")
ax.text(50, 9.4, "Outputs", ha="center", va="top", fontweight="bold", fontsize=7.6)
outs = ["Line-anchored findings", "In-place PDF editor", "Apply-all suggestions", "Mock interview (3 rounds)",
        "Exports: own-layout PDF, DOCX, .tex", "Optional account history"]
for i, o in enumerate(outs):
    ax.text(8 + (i % 3) * 31, 5.0 if i < 3 else 2.3, "• " + o, ha="left", va="center", fontsize=6.6)

arrow((18.2, 27), (21, 34)); arrow((18.2, 18), (21, 20)); arrow((43, 38), (47, 38))
arrow((58, 30), (58, 27.6)); arrow((69, 20), (73, 20)); arrow((69, 38), (73, 38))
arrow((86, 30), (86, 27.6))
arrow((32, 13), (32, 10.3)); arrow((58, 13), (58, 10.3)); arrow((86, 13), (86, 10.3))
ax.text(58, 47.2, "Everything runs on the user's machine; outbound calls are opt-in.", ha="center", fontsize=6.6,
        style="italic")

fig.savefig(OUT / "fig_architecture.pdf", bbox_inches="tight")
fig.savefig(OUT / "fig_architecture.png", bbox_inches="tight", dpi=300)
print("wrote fig_architecture")
