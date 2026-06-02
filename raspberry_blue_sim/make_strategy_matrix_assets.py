import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


RASPBERRY = "#d4485b"
BLUEBERRY = "#3567d6"
GREEN = "#2e7d32"
AMBER = "#c47f00"
RED = "#b91c1c"
NEUTRAL = "#374151"


def read_rows(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = []
        for row in csv.DictReader(f):
            parsed = dict(row)
            for key in ("raspberry_win_rate", "blueberry_win_rate", "avg_final_control", "avg_round_duration"):
                parsed[key] = float(parsed[key])
            rows.append(parsed)
        return rows


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def strategy_order(rows: list[dict]) -> list[str]:
    seen = []
    for row in rows:
        if row["raspberry_strategy"] not in seen:
            seen.append(row["raspberry_strategy"])
    return seen


def save_heatmap(rows: list[dict], strategies: list[str], out: Path) -> None:
    values = []
    labels = {}
    for r_strategy in strategies:
        line = []
        for b_strategy in strategies:
            row = next(
                item
                for item in rows
                if item["raspberry_strategy"] == r_strategy and item["blueberry_strategy"] == b_strategy
            )
            line.append(row["raspberry_win_rate"] * 100)
            labels[(r_strategy, b_strategy)] = row
        values.append(line)

    fig, ax = plt.subplots(figsize=(10.8, 8.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    im = ax.imshow(values, cmap="RdBu_r", vmin=0, vmax=100)
    ax.set_xticks(range(len(strategies)), labels=strategies, rotation=35, ha="right")
    ax.set_yticks(range(len(strategies)), labels=strategies)
    ax.set_xlabel("Blueberry strategy", fontsize=12, weight="bold")
    ax.set_ylabel("Raspberry strategy", fontsize=12, weight="bold")
    ax.set_title("Strategy Matchup Matrix: Raspberry Win Rate", fontsize=18, weight="bold", pad=18)

    for y, r_strategy in enumerate(strategies):
        for x, b_strategy in enumerate(strategies):
            value = values[y][x]
            color = "white" if value < 25 or value > 75 else "#111827"
            ax.text(x, y, f"{value:.1f}%", ha="center", va="center", color=color, weight="bold", fontsize=9)

    cbar = fig.colorbar(im, ax=ax, shrink=0.82)
    cbar.set_label("Raspberry win rate (%)", rotation=270, labelpad=18)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def summarize_by_strategy(rows: list[dict], strategies: list[str]) -> tuple[list[dict], list[dict]]:
    raspberry = []
    blueberry = []
    for strategy in strategies:
        r_rates = [row["raspberry_win_rate"] for row in rows if row["raspberry_strategy"] == strategy]
        b_rates = [row["blueberry_win_rate"] for row in rows if row["blueberry_strategy"] == strategy]
        raspberry.append(
            {
                "strategy": strategy,
                "avg_win_rate": sum(r_rates) / len(r_rates),
                "min_win_rate": min(r_rates),
                "max_win_rate": max(r_rates),
            }
        )
        blueberry.append(
            {
                "strategy": strategy,
                "avg_win_rate": sum(b_rates) / len(b_rates),
                "min_win_rate": min(b_rates),
                "max_win_rate": max(b_rates),
            }
        )
    return raspberry, blueberry


def save_strategy_average_chart(raspberry: list[dict], blueberry: list[dict], out: Path) -> None:
    strategies = [row["strategy"] for row in raspberry]
    x = list(range(len(strategies)))
    width = 0.36
    r_values = [row["avg_win_rate"] * 100 for row in raspberry]
    b_values = [row["avg_win_rate"] * 100 for row in blueberry]

    fig, ax = plt.subplots(figsize=(12, 6.5), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.axhspan(35, 65, color="#e8f5e9", alpha=0.9, label="Viable band: 35-65%")
    ax.axhline(50, color="#111827", linewidth=1.3, linestyle="--", alpha=0.8)
    ax.bar([i - width / 2 for i in x], r_values, width=width, color=RASPBERRY, label="Raspberry as strategy")
    ax.bar([i + width / 2 for i in x], b_values, width=width, color=BLUEBERRY, label="Blueberry as strategy")

    for i, value in enumerate(r_values):
        ax.text(i - width / 2, value + 1.2, f"{value:.1f}", ha="center", fontsize=8, weight="bold")
    for i, value in enumerate(b_values):
        ax.text(i + width / 2, value + 1.2, f"{value:.1f}", ha="center", fontsize=8, weight="bold")

    ax.set_xticks(x, strategies, rotation=20, ha="right")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Average win rate across opponents (%)", fontsize=12)
    ax.set_title("Strategy Portfolio Viability by Team", fontsize=18, weight="bold", pad=16)
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.65)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def save_problem_matchups(rows: list[dict], out: Path) -> list[dict]:
    problems = []
    for row in rows:
        gap = abs(row["raspberry_win_rate"] - 0.5)
        if gap < 0.30:
            continue
        problems.append(
            {
                "raspberry_strategy": row["raspberry_strategy"],
                "blueberry_strategy": row["blueberry_strategy"],
                "raspberry_win_rate": round(row["raspberry_win_rate"], 4),
                "blueberry_win_rate": round(row["blueberry_win_rate"], 4),
                "gap_from_50": round(gap, 4),
                "avg_final_control": round(row["avg_final_control"], 4),
                "issue": "raspberry_overpowered" if row["raspberry_win_rate"] > 0.5 else "blueberry_overpowered",
            }
        )
    problems.sort(key=lambda item: item["gap_from_50"], reverse=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "raspberry_strategy",
            "blueberry_strategy",
            "raspberry_win_rate",
            "blueberry_win_rate",
            "gap_from_50",
            "avg_final_control",
            "issue",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(problems)
    return problems


def save_summary_card(summary: dict, problems: list[dict], out: Path) -> None:
    score = summary["score"]
    lines = [
        ("Avg Raspberry win rate", f"{score['avg_raspberry_win_rate'] * 100:.1f}%"),
        ("Weakest strategy avg", f"{score['weakest_strategy_avg_win_rate'] * 100:.1f}%"),
        ("Strongest strategy avg", f"{score['strongest_strategy_avg_win_rate'] * 100:.1f}%"),
        ("Strategy spread", f"{score['strategy_win_rate_spread'] * 100:.1f}%p"),
        ("Mirror matchup gap", f"{score['avg_mirror_gap'] * 100:.1f}%p"),
        ("Problem matchups", str(len(problems))),
    ]

    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.axis("off")
    ax.set_title("Strategy Matrix Diagnosis", fontsize=20, weight="bold", pad=16)
    table = ax.table(
        cellText=lines,
        colLabels=["Metric", "Value"],
        loc="center",
        cellLoc="center",
        colLoc="center",
        colWidths=[0.58, 0.28],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(13)
    table.scale(1.0, 1.8)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if row == 0:
            cell.set_facecolor("#111827")
            cell.set_text_props(color="white", weight="bold")
        elif row in {2, 3, 4, 5, 6}:
            cell.set_facecolor("#fff7ed")
        else:
            cell.set_facecolor("#ffffff")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def write_strategy_average_csv(path: Path, raspberry: list[dict], blueberry: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["team", "strategy", "avg_win_rate", "min_win_rate", "max_win_rate"])
        for team, rows in (("raspberry", raspberry), ("blueberry", blueberry)):
            for row in rows:
                writer.writerow(
                    [
                        team,
                        row["strategy"],
                        round(row["avg_win_rate"], 4),
                        round(row["min_win_rate"], 4),
                        round(row["max_win_rate"], 4),
                    ]
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-dir", default="raspberry_blue_sim/strategy_matrix_v1_from_strategy_diversity_balance")
    parser.add_argument("--out", default="raspberry_blue_sim/presentation_assets_strategy_matrix_v1")
    args = parser.parse_args()

    matrix_dir = Path(args.matrix_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_rows(matrix_dir / "strategy_matrix.csv")
    summary = read_json(matrix_dir / "strategy_matrix_summary.json")
    strategies = strategy_order(rows)
    raspberry, blueberry = summarize_by_strategy(rows, strategies)
    problems = save_problem_matchups(rows, out_dir / "strategy_problem_matchups.csv")

    save_heatmap(rows, strategies, out_dir / "strategy_matrix_heatmap.png")
    save_strategy_average_chart(raspberry, blueberry, out_dir / "strategy_average_win_rates.png")
    save_summary_card(summary, problems, out_dir / "strategy_matrix_summary_card.png")
    write_strategy_average_csv(out_dir / "strategy_average_win_rates.csv", raspberry, blueberry)

    report = {
        "source_matrix": str(matrix_dir),
        "score": summary["score"],
        "problem_matchups": len(problems),
        "dead_or_weak_strategies": [
            {"team": "raspberry", **row}
            for row in raspberry
            if row["avg_win_rate"] < 0.35
        ]
        + [
            {"team": "blueberry", **row}
            for row in blueberry
            if row["avg_win_rate"] < 0.35
        ],
        "overpowered_strategies": [
            {"team": "raspberry", **row}
            for row in raspberry
            if row["avg_win_rate"] > 0.65
        ]
        + [
            {"team": "blueberry", **row}
            for row in blueberry
            if row["avg_win_rate"] > 0.65
        ],
    }
    (out_dir / "strategy_matrix_asset_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
