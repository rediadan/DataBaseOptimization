import argparse
import csv
import json
from pathlib import Path

from balance import apply_adjustments, reset_balance
from config import TEAMS
from run_experiment import build_summary, write_matches, write_rounds, write_unit_stats
from simulator import run_matches


STRATEGIES = [
    "tank_focus",
    "ranged_focus",
    "swarm_focus",
    "special_focus",
    "upgrade_focus",
    "mixed",
]


def agent_map(raspberry_strategy: str, blueberry_strategy: str) -> dict:
    return {
        "raspberry": f"strategy:{raspberry_strategy}",
        "blueberry": f"strategy:{blueberry_strategy}",
    }


def load_balance(path: str) -> None:
    reset_balance()
    if not path:
        return
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_adjustments(payload.get("accepted_adjustments", []))


def matrix_score(rows: list[dict]) -> dict:
    raspberry_rates = [float(row["raspberry_win_rate"]) for row in rows]
    low_team_strategy_rates = []
    dominant_gaps = []
    for strategy in STRATEGIES:
        raspberry_as_strategy = [
            float(row["raspberry_win_rate"])
            for row in rows
            if row["raspberry_strategy"] == strategy
        ]
        blueberry_as_strategy = [
            float(row["blueberry_win_rate"])
            for row in rows
            if row["blueberry_strategy"] == strategy
        ]
        combined = raspberry_as_strategy + blueberry_as_strategy
        if combined:
            low_team_strategy_rates.append(sum(combined) / len(combined))
        mirror = [
            row for row in rows
            if row["raspberry_strategy"] == strategy and row["blueberry_strategy"] == strategy
        ]
        if mirror:
            dominant_gaps.append(abs(float(mirror[0]["raspberry_win_rate"]) - 0.5))

    avg_raspberry = sum(raspberry_rates) / len(raspberry_rates) if raspberry_rates else 0.0
    weakest_strategy = min(low_team_strategy_rates) if low_team_strategy_rates else 0.0
    strongest_strategy = max(low_team_strategy_rates) if low_team_strategy_rates else 0.0
    strategy_spread = strongest_strategy - weakest_strategy
    avg_mirror_gap = sum(dominant_gaps) / len(dominant_gaps) if dominant_gaps else 0.0
    return {
        "avg_raspberry_win_rate": round(avg_raspberry, 4),
        "weakest_strategy_avg_win_rate": round(weakest_strategy, 4),
        "strongest_strategy_avg_win_rate": round(strongest_strategy, 4),
        "strategy_win_rate_spread": round(strategy_spread, 4),
        "avg_mirror_gap": round(avg_mirror_gap, 4),
        "matrix_balance_penalty": round(abs(avg_raspberry - 0.5) + strategy_spread + avg_mirror_gap, 6),
    }


def write_matrix(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "raspberry_strategy",
            "blueberry_strategy",
            "raspberry_win_rate",
            "blueberry_win_rate",
            "avg_final_control",
            "avg_round_duration",
            "raspberry_detected_dominant",
            "blueberry_detected_dominant",
            "strategy_diversity_penalty",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_matrix_report(path: Path, matches: int, strategies: list[str], balance_result: str, rows: list[dict], live: bool = False) -> None:
    report = {
        "matches_per_matchup": matches,
        "strategies": strategies,
        "balance_result": balance_result.replace("\\", "/"),
        "score": matrix_score(rows),
        "rows": rows,
    }
    if live:
        report["live"] = True
        report["completed_matchups"] = len(rows)
        report["total_matchups"] = len(strategies) * len(strategies)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260601)
    parser.add_argument("--out", default="raspberry_blue_sim/strategy_matrix_out")
    parser.add_argument("--balance-result", default="")
    parser.add_argument("--strategies", nargs="*", default=STRATEGIES)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    load_balance(args.balance_result)

    rows = []
    for r_index, raspberry_strategy in enumerate(args.strategies):
        for b_index, blueberry_strategy in enumerate(args.strategies):
            matchup_dir = out_dir / f"{raspberry_strategy}_vs_{blueberry_strategy}"
            matchup_dir.mkdir(parents=True, exist_ok=True)
            seed = args.seed + r_index * 1000 + b_index * 37
            match_rows, round_rows, aggregate = run_matches(
                args.matches,
                seed,
                agent_map(raspberry_strategy, blueberry_strategy),
                progress_label=f"{raspberry_strategy} vs {blueberry_strategy}",
                progress_updates=2,
            )
            write_matches(matchup_dir / "matches.csv", match_rows)
            write_rounds(matchup_dir / "rounds.csv", round_rows)
            write_unit_stats(matchup_dir / "unit_stats.csv", aggregate, args.matches)
            summary = build_summary(
                match_rows,
                round_rows,
                aggregate,
                args.matches,
                f"strategy_matrix:{raspberry_strategy}_vs_{blueberry_strategy}",
            )
            (matchup_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            row = {
                "raspberry_strategy": raspberry_strategy,
                "blueberry_strategy": blueberry_strategy,
                "raspberry_win_rate": summary["match_win_rate"]["raspberry"],
                "blueberry_win_rate": summary["match_win_rate"]["blueberry"],
                "avg_final_control": summary["avg_final_control"],
                "avg_round_duration": summary["avg_round_duration"],
                "raspberry_detected_dominant": dominant_detected_strategy(summary, "raspberry"),
                "blueberry_detected_dominant": dominant_detected_strategy(summary, "blueberry"),
                "strategy_diversity_penalty": summary["strategy_diversity"]["score"],
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            write_matrix(out_dir / "strategy_matrix.csv", rows)
            write_matrix_report(
                out_dir / "strategy_matrix_summary.json",
                args.matches,
                args.strategies,
                args.balance_result,
                rows,
                live=len(rows) < len(args.strategies) * len(args.strategies),
            )

    report = {
        "matches_per_matchup": args.matches,
        "strategies": args.strategies,
        "balance_result": args.balance_result,
        "score": matrix_score(rows),
        "rows": rows,
    }
    write_matrix_report(out_dir / "strategy_matrix_summary.json", args.matches, args.strategies, args.balance_result, rows)
    print(json.dumps(report["score"], ensure_ascii=False, indent=2))
    print(f"wrote: {out_dir}")


def dominant_detected_strategy(summary: dict, team: str) -> str:
    counts = summary.get("strategy_diversity", {}).get("by_team", {}).get(team, {}).get("strategy_counts", {})
    if not counts:
        return ""
    return max(counts, key=counts.get)


if __name__ == "__main__":
    main()
