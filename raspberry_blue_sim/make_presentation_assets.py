import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt

from config import TEAMS


RASPBERRY = "#d4485b"
BLUEBERRY = "#3567d6"
NEUTRAL = "#4b5563"
GREEN = "#2e7d32"
AMBER = "#c47f00"


def read_history(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = []
        for row in csv.DictReader(f):
            parsed = dict(row)
            for key in (
                "iteration",
                "raspberry_win_rate",
                "blueberry_win_rate",
                "avg_final_control",
                "avg_round_duration",
                "balance_score",
                "confirmation_raspberry_win_rate",
                "confirmation_blueberry_win_rate",
                "confirmation_avg_final_control",
                "confirmation_balance_score",
            ):
                if parsed.get(key) not in ("", None):
                    parsed[key] = float(parsed[key])
            rows.append(parsed)
        return rows


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def annotate_last(ax, x, y, text, color):
    ax.scatter([x], [y], s=80, color=color, zorder=5)
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(8, 8),
        textcoords="offset points",
        fontsize=10,
        color=color,
        weight="bold",
    )


def save_win_rate_chart(history: list[dict], out: Path) -> None:
    xs = [int(row["iteration"]) for row in history]
    r = [row["raspberry_win_rate"] * 100 for row in history]
    b = [row["blueberry_win_rate"] * 100 for row in history]

    fig, ax = plt.subplots(figsize=(12, 6.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.axhspan(44, 56, color="#e8f5e9", alpha=0.95, label="Target band: 50% ± 6%")
    ax.axhline(50, color="#111827", linewidth=1.4, linestyle="--", alpha=0.75)
    ax.plot(xs, r, marker="o", linewidth=2.8, color=RASPBERRY, label="Raspberry win rate")
    ax.plot(xs, b, marker="o", linewidth=2.8, color=BLUEBERRY, label="Blueberry win rate")
    annotate_last(ax, xs[-1], r[-1], f"{r[-1]:.1f}%", RASPBERRY)
    annotate_last(ax, xs[-1], b[-1], f"{b[-1]:.1f}%", BLUEBERRY)

    last = history[-1]
    if last.get("confirmation_raspberry_win_rate", "") != "":
        cx = xs[-1] + 0.35
        cr = last["confirmation_raspberry_win_rate"] * 100
        cb = last["confirmation_blueberry_win_rate"] * 100
        ax.scatter([cx], [cr], marker="D", s=80, color=RASPBERRY, edgecolors="#111827", zorder=6)
        ax.scatter([cx], [cb], marker="D", s=80, color=BLUEBERRY, edgecolors="#111827", zorder=6)
        ax.annotate("confirmation", xy=(cx, cr), xytext=(10, 14), textcoords="offset points", fontsize=9)

    ax.set_title("Balance Learning Result: Win Rate Converged Near 50%", fontsize=18, weight="bold", pad=16)
    ax.set_xlabel("Balance iteration", fontsize=12)
    ax.set_ylabel("Match win rate (%)", fontsize=12)
    ax.set_ylim(0, 104)
    ax.set_xticks(xs)
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.75)
    ax.legend(loc="upper right", frameon=True)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def save_control_score_chart(history: list[dict], out: Path) -> None:
    xs = [int(row["iteration"]) for row in history]
    control = [row["avg_final_control"] for row in history]
    score = [row["balance_score"] for row in history]

    fig, ax1 = plt.subplots(figsize=(12, 6.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax1.set_facecolor("#ffffff")
    ax1.axhline(0, color="#111827", linewidth=1.2, linestyle="--", alpha=0.7)
    ax1.plot(xs, control, marker="o", linewidth=2.8, color=NEUTRAL, label="Avg final control")
    ax1.set_ylabel("Average final control", fontsize=12, color=NEUTRAL)
    ax1.tick_params(axis="y", labelcolor=NEUTRAL)
    ax1.set_ylim(-3.2, 3.2)
    ax1.set_xticks(xs)
    ax1.set_xlabel("Balance iteration", fontsize=12)
    ax1.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.7)

    ax2 = ax1.twinx()
    ax2.plot(xs, score, marker="s", linewidth=2.4, color=AMBER, label="Balance score")
    ax2.set_ylabel("Balance score, lower is better", fontsize=12, color=AMBER)
    ax2.tick_params(axis="y", labelcolor=AMBER)
    ax2.set_ylim(0, max(score) * 1.15 if score else 1)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.set_title("Territory Control and Balance Score Improved Together", fontsize=18, weight="bold", pad=16)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def save_final_validation_card(history: list[dict], result: dict, out: Path) -> None:
    last = history[-1]
    values = [
        last["raspberry_win_rate"] * 100,
        last["blueberry_win_rate"] * 100,
        last["confirmation_raspberry_win_rate"] * 100,
        last["confirmation_blueberry_win_rate"] * 100,
    ]
    labels = ["R first", "B first", "R confirm", "B confirm"]
    colors = [RASPBERRY, BLUEBERRY, RASPBERRY, BLUEBERRY]

    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.set_facecolor("#ffffff")
    bars = ax.bar(labels, values, color=colors, alpha=0.92)
    ax.axhspan(44, 56, color="#e8f5e9", alpha=0.95)
    ax.axhline(50, color="#111827", linewidth=1.4, linestyle="--")
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 1.5, f"{value:.1f}%", ha="center", weight="bold")

    ax.set_ylim(0, 100)
    ax.set_ylabel("Win rate (%)", fontsize=12)
    ax.set_title("Final Patch Passed Independent Confirmation", fontsize=18, weight="bold", pad=16)
    ax.text(
        0.5,
        -0.16,
        (
            f"Iterations: {result['iterations_completed']} | "
            f"Initial playouts: {result['initial_playouts']} | "
            f"Validation: {result['validation_matches']} x {result['validation_seeds']} seeds | "
            f"Confirmation: {result['validation_matches']} x {result['confirmation_seeds']} seeds"
        ),
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color="#374151",
    )
    ax.grid(axis="y", color="#d1d5db", linewidth=0.8, alpha=0.65)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def save_patch_table_image(result: dict, out: Path) -> None:
    units = result["final_units"]
    rows = []
    for team, specs in units.items():
        for spec in specs:
            rows.append(
                [
                    "Raspberry" if team == "raspberry" else "Blueberry",
                    spec["key"],
                    spec["cost"],
                    spec["hp"],
                    spec["speed"],
                    spec["power"],
                    spec["cooldown"],
                    spec["range"],
                    spec["area"],
                ]
            )

    fig, ax = plt.subplots(figsize=(14, 5.8), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.axis("off")
    ax.set_title("Final Unit Stats After Confirmed Balance Patch", fontsize=18, weight="bold", pad=16)
    table = ax.table(
        cellText=rows,
        colLabels=["Team", "Unit", "Cost", "HP", "Speed", "Power", "Cooldown", "Range", "Area"],
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.2)
    table.scale(1, 1.45)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if row == 0:
            cell.set_facecolor("#111827")
            cell.set_text_props(color="white", weight="bold")
        elif row <= 5:
            cell.set_facecolor("#fff1f2")
        else:
            cell.set_facecolor("#eff6ff")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def base_unit_map() -> dict[tuple[str, str], dict]:
    units = {}
    for team, team_data in TEAMS.items():
        for spec in team_data["units"]:
            units[(team, spec.key)] = {
                "cost": spec.cost,
                "hp": spec.hp,
                "speed": spec.speed,
                "power": spec.power,
                "cooldown": spec.cooldown,
                "range": spec.range,
                "area": spec.area,
            }
    return units


def final_unit_map(result: dict) -> dict[tuple[str, str], dict]:
    units = {}
    for team, specs in result["final_units"].items():
        for spec in specs:
            units[(team, spec["key"])] = {
                "cost": spec["cost"],
                "hp": spec["hp"],
                "speed": spec["speed"],
                "power": spec["power"],
                "cooldown": spec["cooldown"],
                "range": spec["range"],
                "area": spec["area"],
            }
    return units


def fmt_value(value) -> str:
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def fmt_change(before, after) -> str:
    before_f = float(before)
    after_f = float(after)
    if abs(before_f - after_f) < 1e-9:
        return fmt_value(after)
    return f"{fmt_value(before)} -> {fmt_value(after)}"


def changed(before, after) -> bool:
    return abs(float(before) - float(after)) > 1e-9


def change_kind(stat: str, before, after) -> str:
    before_f = float(before)
    after_f = float(after)
    if abs(before_f - after_f) < 1e-9:
        return "unchanged"
    lower_is_better = stat in {"cost", "cooldown"}
    if lower_is_better:
        return "buff" if after_f < before_f else "debuff"
    return "buff" if after_f > before_f else "debuff"


def save_before_after_csv(result: dict, out: Path) -> None:
    base = base_unit_map()
    final = final_unit_map(result)
    stats = ["cost", "hp", "speed", "power", "cooldown", "range", "area"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["team", "unit", "stat", "before", "after", "change", "change_percent", "effect"])
        for team in ("raspberry", "blueberry"):
            for spec in TEAMS[team]["units"]:
                unit_key = spec.key
                for stat in stats:
                    before = base[(team, unit_key)][stat]
                    after = final[(team, unit_key)][stat]
                    delta = float(after) - float(before)
                    pct = "" if float(before) == 0 else round(delta / float(before) * 100, 2)
                    writer.writerow([team, unit_key, stat, before, after, round(delta, 4), pct, change_kind(stat, before, after)])


def save_before_after_image(result: dict, out: Path) -> None:
    base = base_unit_map()
    final = final_unit_map(result)
    stats = ["cost", "hp", "speed", "power", "cooldown", "range", "area"]
    rows = []
    effect_matrix = []
    for team in ("raspberry", "blueberry"):
        for spec in TEAMS[team]["units"]:
            unit_key = spec.key
            row = ["Raspberry" if team == "raspberry" else "Blueberry", unit_key]
            row_effects = ["meta", "meta"]
            for stat in stats:
                before = base[(team, unit_key)][stat]
                after = final[(team, unit_key)][stat]
                row.append(fmt_change(before, after))
                row_effects.append(change_kind(stat, before, after))
            rows.append(row)
            effect_matrix.append(row_effects)

    fig, ax = plt.subplots(figsize=(17, 7.2), dpi=160)
    fig.patch.set_facecolor("#f8fafc")
    ax.axis("off")
    ax.set_title("Unit Stat Changes: Before -> After Confirmed Patch", fontsize=18, weight="bold", pad=16)
    table = ax.table(
        cellText=rows,
        colLabels=["Team", "Unit", "Cost", "HP", "Speed", "Power", "Cooldown", "Range", "Area"],
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.4)
    table.scale(1, 1.55)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d1d5db")
        if row == 0:
            cell.set_facecolor("#111827")
            cell.set_text_props(color="white", weight="bold")
            continue
        if col <= 1:
            cell.set_facecolor("#fff1f2" if row <= 5 else "#eff6ff")
            cell.set_text_props(weight="bold")
        elif effect_matrix[row - 1][col] == "buff":
            cell.set_facecolor("#dcfce7")
            cell.set_text_props(color="#166534", weight="bold")
        elif effect_matrix[row - 1][col] == "debuff":
            cell.set_facecolor("#fee2e2")
            cell.set_text_props(color="#991b1b", weight="bold")
        else:
            cell.set_facecolor("#f9fafb")
            cell.set_text_props(color="#6b7280")
    ax.text(
        0.5,
        0.02,
        "Green = buff for that unit, red = debuff for that unit. Cost/Cooldown decrease counts as buff.",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        color="#374151",
    )
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    history = read_history(run_dir / "master_history.csv")
    result = read_json(run_dir / "final_result.json")

    save_win_rate_chart(history, out_dir / "v4_win_rate_convergence.png")
    save_control_score_chart(history, out_dir / "v4_control_balance_score.png")
    save_final_validation_card(history, result, out_dir / "v4_final_confirmation.png")
    save_patch_table_image(result, out_dir / "v4_final_unit_stats.png")
    save_before_after_image(result, out_dir / "v4_unit_stats_before_after.png")
    save_before_after_csv(result, out_dir / "v4_unit_stats_before_after.csv")

    print(f"wrote assets to: {out_dir}")


if __name__ == "__main__":
    main()
