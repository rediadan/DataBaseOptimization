import argparse
import json
from pathlib import Path

from balance import apply_adjustments, reset_balance
from config import TEAMS
from simulator import load_policy, run_matches, save_policy


def policy_summary(policy: dict) -> dict:
    summary = {}
    for team in TEAMS:
        states = policy.get(team, {})
        action_nodes = 0
        visits = 0
        best_actions = {}
        for state in states.values():
            action_nodes += len(state)
            for action_key, node in state.items():
                visits += node.get("visits", 0)
                best_actions[action_key] = best_actions.get(action_key, 0) + node.get("visits", 0)
        summary[team] = {
            "states": len(states),
            "action_nodes": action_nodes,
            "visits": visits,
            "most_visited_actions": sorted(best_actions.items(), key=lambda item: item[1], reverse=True)[:8],
        }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--playouts", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--policy-out", default="raspberry_blue_sim/policies/mcts_policy.json")
    parser.add_argument("--resume", default="")
    parser.add_argument("--balance-result", default="")
    parser.add_argument("--report-out", default="raspberry_blue_sim/policies/mcts_policy_summary.json")
    args = parser.parse_args()

    applied_adjustments = []
    if args.balance_result:
        reset_balance()
        balance_result = json.loads(Path(args.balance_result).read_text(encoding="utf-8"))
        applied_adjustments = balance_result.get("accepted_adjustments", [])
        apply_adjustments(applied_adjustments)

    policy = load_policy(args.resume)
    match_rows, round_rows, aggregate = run_matches(args.playouts, args.seed, "policy_train", policy)
    save_policy(args.policy_out, policy)

    wins = {team: sum(1 for row in match_rows if row.winner == team) for team in TEAMS}
    report = {
        "playouts": args.playouts,
        "seed": args.seed,
        "balance_result": args.balance_result,
        "applied_adjustments": applied_adjustments,
        "match_wins_during_training": wins,
        "match_win_rate_during_training": {team: round(wins[team] / args.playouts, 4) for team in TEAMS},
        "rounds_played": len(round_rows),
        "avg_final_upgrades_per_match": {
            team: round(aggregate[team].upgrade_level / args.playouts, 4) for team in TEAMS
        },
        "policy": policy_summary(policy),
    }

    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"policy wrote: {args.policy_out}")
    print(f"report wrote: {args.report_out}")


if __name__ == "__main__":
    main()
