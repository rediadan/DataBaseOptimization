import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLORS = {"before": "#4C78A8", "after": "#F58518", "raspberry": "#D64F6F", "blueberry": "#4C78A8"}


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def as_float(row: dict, key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in {"", None} else 0.0


def label_bars(ax, bars, fmt="{:.2f}"):
    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            fmt.format(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=9,
        )


def save_grouped_bar(path: Path, title: str, labels: list[str], before: list[float], after: list[float], ylabel: str):
    x = list(range(len(labels)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.75), 5))
    before_bars = ax.bar([i - width / 2 for i in x], before, width, label="Before", color=COLORS["before"])
    after_bars = ax.bar([i + width / 2 for i in x], after, width, label="After", color=COLORS["after"])
    label_bars(ax, before_bars)
    label_bars(ax, after_bars)
    ax.set_title(title, fontsize=15, weight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def metric_lookup(summary_rows: list[dict]) -> dict[str, dict]:
    return {row["metric"]: row for row in summary_rows}


def plot_win_rate(summary_rows: list[dict], out: Path):
    rows = metric_lookup(summary_rows)
    labels = ["Raspberry", "Blueberry"]
    before = [as_float(rows["raspberry_win_rate"], "before"), as_float(rows["blueberry_win_rate"], "before")]
    after = [as_float(rows["raspberry_win_rate"], "after"), as_float(rows["blueberry_win_rate"], "after")]
    save_grouped_bar(out / "win_rate_before_after.png", "Match Win Rate Before/After", labels, before, after, "Win rate")


def plot_avg_control(summary_rows: list[dict], out: Path):
    rows = metric_lookup(summary_rows)
    save_grouped_bar(
        out / "avg_control_before_after.png",
        "Average Final Control Before/After",
        ["Avg final control"],
        [as_float(rows["avg_final_control"], "before")],
        [as_float(rows["avg_final_control"], "after")],
        "Control (-3 blueberry, +3 raspberry)",
    )


def unit_labels(rows: list[dict]) -> list[str]:
    return [f"{row['team']}.{row['unit_key']}" for row in rows]


def plot_unit_metric(rows: list[dict], out: Path, metric: str, filename: str, title: str, ylabel: str, top: int = 10):
    ordered = sorted(rows, key=lambda row: max(as_float(row, f"{metric}_before"), as_float(row, f"{metric}_after")), reverse=True)[:top]
    labels = unit_labels(ordered)
    before = [as_float(row, f"{metric}_before") for row in ordered]
    after = [as_float(row, f"{metric}_after") for row in ordered]
    save_grouped_bar(out / filename, title, labels, before, after, ylabel)


def plot_focus(rows: list[dict], out: Path):
    ordered = sorted(rows, key=lambda row: max(as_float(row, "focus_fire_events_before"), as_float(row, "focus_fire_events_after")), reverse=True)[:10]
    labels = unit_labels(ordered)
    before = [as_float(row, "focus_fire_events_before") for row in ordered]
    after = [as_float(row, "focus_fire_events_after") for row in ordered]
    save_grouped_bar(out / "focus_fire_before_after.png", "Focus Fire Events Before/After", labels, before, after, "Events")


def plot_history(history_rows: list[dict], out: Path):
    accepted = [row for row in history_rows if row.get("accepted") == "True"]
    if not accepted:
        accepted = history_rows
    labels = [str(row["iteration"]) for row in accepted]
    scores = [as_float(row, "score") for row in accepted]
    raspberry = [as_float(row, "raspberry_win_rate") for row in accepted]
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.plot(labels, scores, marker="o", color="#333333", label="Score")
    ax1.set_ylabel("Balance score")
    ax1.set_xlabel("Accepted iteration")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(labels, raspberry, marker="s", color=COLORS["raspberry"], label="Raspberry win rate")
    ax2.axhline(0.5, color="#888888", linestyle="--", linewidth=1)
    ax2.set_ylabel("Raspberry win rate")
    fig.suptitle("Balance Optimization History", fontsize=15, weight="bold")
    lines, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels1 + labels2, loc="best")
    fig.tight_layout()
    fig.savefig(out / "balance_score_history.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    compare_dir = Path(args.compare)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = read_csv(compare_dir / "comparison_summary.csv")
    units = read_csv(compare_dir / "unit_usage_comparison.csv")
    history = read_csv(Path(args.history))

    plot_win_rate(summary, out_dir)
    plot_avg_control(summary, out_dir)
    plot_unit_metric(units, out_dir, "produced_per_match", "unit_usage_before_after.png", "Unit Production Per Match", "Units per match")
    plot_unit_metric(units, out_dir, "damage_per_match", "unit_damage_before_after.png", "Unit Damage Per Match", "Damage per match")
    plot_focus(units, out_dir)
    plot_history(history, out_dir)
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
