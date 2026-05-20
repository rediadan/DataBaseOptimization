import argparse
import csv
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def as_float(row: dict, key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in {"", None} else 0.0


def write_summary(before: dict, after: dict, path: Path) -> None:
    rows = [
        ("raspberry_win_rate", before["match_win_rate"]["raspberry"], after["match_win_rate"]["raspberry"]),
        ("blueberry_win_rate", before["match_win_rate"]["blueberry"], after["match_win_rate"]["blueberry"]),
        ("raspberry_round_wins", before["round_wins"]["raspberry"], after["round_wins"]["raspberry"]),
        ("blueberry_round_wins", before["round_wins"]["blueberry"], after["round_wins"]["blueberry"]),
        ("avg_final_control", before["avg_final_control"], after["avg_final_control"]),
        ("avg_round_duration", before["avg_round_duration"], after["avg_round_duration"]),
        (
            "raspberry_avg_upgrades",
            before["avg_final_upgrades_per_match"]["raspberry"],
            after["avg_final_upgrades_per_match"]["raspberry"],
        ),
        (
            "blueberry_avg_upgrades",
            before["avg_final_upgrades_per_match"]["blueberry"],
            after["avg_final_upgrades_per_match"]["blueberry"],
        ),
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "before", "after", "delta"])
        for metric, before_value, after_value in rows:
            writer.writerow([metric, before_value, after_value, round(after_value - before_value, 6)])


def index_units(rows: list[dict]) -> dict[tuple[str, str], dict]:
    return {(row["team"], row["unit_key"]): row for row in rows}


def write_unit_comparison(before_rows: list[dict], after_rows: list[dict], path: Path) -> None:
    before = index_units(before_rows)
    after = index_units(after_rows)
    keys = sorted(set(before) | set(after))
    metrics = [
        "produced_per_match",
        "team_production_share",
        "kills_per_match",
        "damage_per_match",
        "healing",
        "avg_survival_time",
        "focus_fire_hits",
        "focus_fire_events",
        "max_focus_attackers",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["team", "unit_key", "unit_name"]
        for metric in metrics:
            header.extend([f"{metric}_before", f"{metric}_after", f"{metric}_delta"])
        writer.writerow(header)
        for key in keys:
            before_row = before.get(key, {})
            after_row = after.get(key, {})
            unit_name = after_row.get("unit_name") or before_row.get("unit_name") or key[1]
            row = [key[0], key[1], unit_name]
            for metric in metrics:
                before_value = as_float(before_row, metric)
                after_value = as_float(after_row, metric)
                row.extend([round(before_value, 6), round(after_value, 6), round(after_value - before_value, 6)])
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    before_dir = Path(args.before)
    after_dir = Path(args.after)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_summary(
        read_json(before_dir / "summary.json"),
        read_json(after_dir / "summary.json"),
        out_dir / "comparison_summary.csv",
    )
    write_unit_comparison(
        read_csv(before_dir / "unit_stats.csv"),
        read_csv(after_dir / "unit_stats.csv"),
        out_dir / "unit_usage_comparison.csv",
    )
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
