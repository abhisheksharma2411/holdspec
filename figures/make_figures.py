"""Regenerate every figure from the JSON under results/.

No number in a figure is typed here. If a result file is missing, the figure it
feeds is skipped and the script says so, rather than drawing something stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
FIGURES = REPO / "figures"

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.dpi": 200,
        "savefig.bbox": "tight",
    }
)

INK = "#1b2430"
ACCENT = "#2f6f9f"
WARM = "#c2703d"
MUTED = "#8a9099"


def load(name: str):
    path = RESULTS / name
    if not path.exists():
        print(f"  skipped: {name} not found")
        return None
    return json.loads(path.read_text())


def fig_state_space():
    data = load("e1_model_check.json")
    if not data:
        return
    scaling = data["scaling"]
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.5))
    for ax, varied, label, colour in (
        (axes[0], "max_non_final_captures", "non-final capture budget", ACCENT),
        (axes[1], "validity", "validity window (ticks)", WARM),
    ):
        rows = [r for r in scaling if r["varied"] == varied]
        xs = [r["value"] for r in rows]
        ys = [r["distinct_states"] for r in rows]
        ax.plot(xs, ys, marker="o", color=colour, linewidth=1.6, markersize=4)
        ax.set_xlabel(label)
        ax.set_xticks(xs)
        ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    axes[0].set_ylabel("distinct states")
    fig.suptitle("Reachable states as the profile bounds widen", y=1.04, color=INK)
    fig.savefig(FIGURES / "fig1_state_space.pdf")
    fig.savefig(FIGURES / "fig1_state_space.png")
    plt.close(fig)
    print("  fig1_state_space")


def fig_detection():
    data = load("e3_conformance.json")
    if not data:
        return
    rows = data["per_profile"]
    names = [r["profile"].replace("_", "\n") for r in rows]
    suites = [("model", ACCENT), ("handwritten", WARM), ("random", MUTED),
              ("random_10x", "#b9c0c9")]
    width = 0.2
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    for i, (suite, colour) in enumerate(suites):
        vals = [r["detection_rate"][suite] for r in rows]
        xs = [x + (i - 1.5) * width for x in range(len(rows))]
        ax.bar(xs, vals, width=width, label=suite, color=colour, edgecolor="none")
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels(names, fontsize=7)
    ax.set_ylabel("mutants detected")
    ax.set_ylim(0, 1.08)
    ax.axhline(1.0, color=INK, linewidth=0.6, linestyle=":")
    ax.legend(frameon=False, ncol=4, loc="lower right", fontsize=7)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    ax.set_title("Detection of non-equivalent lifecycle defects, by suite", color=INK)
    fig.savefig(FIGURES / "fig2_detection.pdf")
    fig.savefig(FIGURES / "fig2_detection.png")
    plt.close(fig)
    print("  fig2_detection")


def fig_divergence():
    data = load("e4_cross_provider.json")
    if not data:
        return
    pairs = data["all_pairs"]
    names = sorted({p["left"] for p in pairs} | {p["right"] for p in pairs})
    idx = {n: i for i, n in enumerate(names)}
    grid = [[0] * len(names) for _ in names]
    for row in pairs:
        i, j = idx[row["left"]], idx[row["right"]]
        grid[i][j] = grid[j][i] = row["divergence_classes"]

    short = [n.replace("_captures", "").replace("_", " ") for n in names]
    fig, ax = plt.subplots(figsize=(4.4, 3.9))
    im = ax.imshow(grid, cmap="BuPu", vmin=0)
    ax.set_xticks(range(len(names)))
    ax.set_yticks(range(len(names)))
    ax.set_xticklabels(short, rotation=40, ha="right", fontsize=6.5)
    ax.set_yticklabels(short, fontsize=6.5)
    for i in range(len(names)):
        for j in range(len(names)):
            if i != j:
                ax.text(j, i, grid[i][j], ha="center", va="center", fontsize=7,
                        color="white" if grid[i][j] > max(max(r) for r in grid) / 2 else INK)
    ax.set_title("Independent behavioral divergences\nbetween provider profiles",
                 fontsize=9, color=INK)
    fig.colorbar(im, ax=ax, shrink=0.7, label="divergence classes")
    fig.savefig(FIGURES / "fig3_divergence.pdf")
    fig.savefig(FIGURES / "fig3_divergence.png")
    plt.close(fig)
    print("  fig3_divergence")


def main() -> int:
    FIGURES.mkdir(parents=True, exist_ok=True)
    print("regenerating figures from results/")
    fig_state_space()
    fig_detection()
    fig_divergence()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
