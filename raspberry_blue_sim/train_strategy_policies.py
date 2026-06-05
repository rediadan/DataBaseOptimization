import argparse
import csv
import json
from pathlib import Path

from balance import apply_adjustments, reset_balance
from config import TEAMS
from run_experiment import build_summary, write_matches, write_rounds, write_unit_stats
from simulator import run_matches, save_policy
from train_mcts import policy_summary


STRATEGIES = [
    "tank_aoe_focus",
    "ranged_focus",
    "swarm_focus",
    "suicide_aoe_focus",
    "upgrade_focus",
    "mixed",
]


def load_balance(path: str) -> list[dict]:
    reset_balance()
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    adjustments = payload.get("accepted_adjustments", [])
    apply_adjustments(adjustments)
    return adjustments


def dominant_detected_strategy(summary: dict, team: str) -> str:
    counts = summary.get("strategy_diversity", {}).get("by_team", {}).get(team, {}).get("strategy_counts", {})
    if not counts:
        return ""
    return max(counts, key=counts.get)


def strategy_count(summary: dict, team: str, strategy: str) -> int:
    key = "mixed_composition" if strategy == "mixed" else strategy
    if strategy in {"healer_support", "suicide_aoe_focus"}:
        key = "special_focus"
    counts = summary.get("strategy_diversity", {}).get("by_team", {}).get(team, {}).get("strategy_counts", {})
    return int(counts.get(key, 0))


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "strategy",
        "playouts",
        "seed",
        "raspberry_win_rate",
        "blueberry_win_rate",
        "avg_final_control",
        "avg_round_duration",
        "raspberry_detected_dominant",
        "blueberry_detected_dominant",
        "raspberry_target_strategy_count",
        "blueberry_target_strategy_count",
        "strategy_diversity_penalty",
        "raspberry_avg_upgrades",
        "blueberry_avg_upgrades",
        "policy_raspberry_states",
        "policy_blueberry_states",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def train_one_strategy(strategy: str, playouts: int, seed: int, out_dir: Path) -> dict:
    strategy_dir = out_dir / strategy
    strategy_dir.mkdir(parents=True, exist_ok=True)
    policy: dict = {}
    agent_type = f"strategy_policy_train:{strategy}"
    match_rows, round_rows, aggregate = run_matches(
        playouts,
        seed,
        agent_type,
        policy,
        progress_label=f"{strategy} policy train",
    )
    policy_path = strategy_dir / f"{strategy}_policy.json"
    save_policy(str(policy_path), policy)
    write_matches(strategy_dir / "matches.csv", match_rows)
    write_rounds(strategy_dir / "rounds.csv", round_rows)
    write_unit_stats(strategy_dir / "unit_stats.csv", aggregate, playouts)
    summary = build_summary(match_rows, round_rows, aggregate, playouts, agent_type)
    summary["policy_path"] = str(policy_path).replace("\\", "/")
    summary["policy"] = policy_summary(policy)
    (strategy_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "strategy": strategy,
        "playouts": playouts,
        "seed": seed,
        "raspberry_win_rate": summary["match_win_rate"]["raspberry"],
        "blueberry_win_rate": summary["match_win_rate"]["blueberry"],
        "avg_final_control": summary["avg_final_control"],
        "avg_round_duration": summary["avg_round_duration"],
        "raspberry_detected_dominant": dominant_detected_strategy(summary, "raspberry"),
        "blueberry_detected_dominant": dominant_detected_strategy(summary, "blueberry"),
        "raspberry_target_strategy_count": strategy_count(summary, "raspberry", strategy),
        "blueberry_target_strategy_count": strategy_count(summary, "blueberry", strategy),
        "strategy_diversity_penalty": summary["strategy_diversity"]["score"],
        "raspberry_avg_upgrades": round(aggregate["raspberry"].upgrade_level / playouts, 4),
        "blueberry_avg_upgrades": round(aggregate["blueberry"].upgrade_level / playouts, 4),
        "policy_raspberry_states": summary["policy"]["raspberry"]["states"],
        "policy_blueberry_states": summary["policy"]["blueberry"]["states"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playouts", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--out", default="raspberry_blue_sim/strategy_policy_runs")
    parser.add_argument("--balance-result", default="")
    parser.add_argument("--strategies", nargs="*", default=STRATEGIES)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    applied_adjustments = load_balance(args.balance_result)

    rows: list[dict] = []
    for index, strategy in enumerate(args.strategies):
        strategy_seed = args.seed + index * 1009
        print(f"[{strategy}] strategy policy training start: playouts={args.playouts}, seed={strategy_seed}", flush=True)
        row = train_one_strategy(strategy, args.playouts, strategy_seed, out_dir)
        rows.append(row)
        write_rows(out_dir / "strategy_policy_training.csv", rows)
        report = {
            "playouts_per_strategy": args.playouts,
            "seed": args.seed,
            "strategies": args.strategies,
            "balance_result": args.balance_result.replace("\\", "/"),
            "applied_adjustments": applied_adjustments,
            "completed_strategies": len(rows),
            "total_strategies": len(args.strategies),
            "live": len(rows) < len(args.strategies),
            "rows": rows,
        }
        (out_dir / "strategy_policy_training_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(row, ensure_ascii=False), flush=True)

    report = {
        "playouts_per_strategy": args.playouts,
        "seed": args.seed,
        "strategies": args.strategies,
        "balance_result": args.balance_result.replace("\\", "/"),
        "applied_adjustments": applied_adjustments,
        "completed_strategies": len(rows),
        "total_strategies": len(args.strategies),
        "live": False,
        "rows": rows,
    }
    (out_dir / "strategy_policy_training_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote: {out_dir}", flush=True)


if __name__ == "__main__":
    main()
