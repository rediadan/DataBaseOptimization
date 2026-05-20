import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from balance import apply_adjustments, compact_adjustment, export_units, reset_balance
from config import TEAMS
from simulator import TeamState, load_policy, run_matches


def evaluate(matches: int, seed: int, agent: str, policy: dict | None) -> tuple[dict, Dict[str, TeamState]]:
    match_rows, round_rows, aggregate = run_matches(matches, seed, agent, policy)
    wins = {team: sum(1 for row in match_rows if row.winner == team) for team in TEAMS}
    round_wins = {team: sum(1 for row in round_rows if row.winner == team) for team in TEAMS}
    summary = {
        "matches": matches,
        "wins": wins,
        "win_rate": {team: wins[team] / matches for team in TEAMS},
        "round_wins": round_wins,
        "avg_final_control": sum(row.final_control for row in round_rows) / len(round_rows) if round_rows else 0.0,
        "avg_round_duration": sum(row.duration for row in round_rows) / len(round_rows) if round_rows else 0.0,
        "avg_upgrades": {team: aggregate[team].upgrade_level / matches for team in TEAMS},
    }
    return summary, aggregate


def score(summary: dict, target: float) -> float:
    win_rate_error = abs(summary["win_rate"]["raspberry"] - target)
    control_error = abs(summary["avg_final_control"]) / 3.0
    return win_rate_error + 0.25 * control_error


def unit_contribution(state: TeamState) -> List[Tuple[str, float]]:
    keys = set(state.produced) | set(state.kills) | set(state.damage) | set(state.healing)
    ranked = []
    for key in keys:
        contribution = (
            state.damage.get(key, 0.0)
            + state.healing.get(key, 0.0) * 0.6
            + state.kills.get(key, 0) * 80
            + state.produced.get(key, 0) * 8
        )
        ranked.append((key, contribution))
    return sorted(ranked, key=lambda item: item[1], reverse=True)


def build_candidates(dominant_team: str, aggregate: Dict[str, TeamState]) -> List[Dict[str, Any]]:
    weaker_team = "raspberry" if dominant_team == "blueberry" else "blueberry"
    ranked_units = [key for key, _ in unit_contribution(aggregate[dominant_team])[:3]]
    weaker_ranked_units = [key for key, _ in unit_contribution(aggregate[weaker_team])[:3]]
    candidates: List[Dict[str, Any]] = []
    for unit_key in ranked_units:
        spec = next(spec for spec in TEAMS[dominant_team]["units"] if spec.key == unit_key)
        if spec.power > 0:
            candidates.append({"team": dominant_team, "unit": unit_key, "stat": "power", "factor": 0.75})
        if spec.hp > 0:
            candidates.append({"team": dominant_team, "unit": unit_key, "stat": "hp", "factor": 0.8})
        if spec.speed > 0:
            candidates.append({"team": dominant_team, "unit": unit_key, "stat": "speed", "factor": 0.85})
        candidates.append({"team": dominant_team, "unit": unit_key, "stat": "cost", "factor": 1.25})
        if spec.area > 0:
            candidates.append({"team": dominant_team, "unit": unit_key, "stat": "area", "factor": 0.75})
    for unit_key in weaker_ranked_units:
        spec = next(spec for spec in TEAMS[weaker_team]["units"] if spec.key == unit_key)
        if spec.power > 0:
            candidates.append({"team": weaker_team, "unit": unit_key, "stat": "power", "factor": 1.2})
        if spec.hp > 0:
            candidates.append({"team": weaker_team, "unit": unit_key, "stat": "hp", "factor": 1.18})
        if spec.speed > 0:
            candidates.append({"team": weaker_team, "unit": unit_key, "stat": "speed", "factor": 1.12})
        candidates.append({"team": weaker_team, "unit": unit_key, "stat": "cost", "factor": 0.85})
        if spec.area > 0:
            candidates.append({"team": weaker_team, "unit": unit_key, "stat": "area", "factor": 1.2})
    return candidates


def write_history(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "iteration",
                "candidate",
                "raspberry_win_rate",
                "blueberry_win_rate",
                "avg_final_control",
                "score",
                "accepted",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["iteration"],
                    row["candidate"],
                    round(row["summary"]["win_rate"]["raspberry"], 4),
                    round(row["summary"]["win_rate"]["blueberry"], 4),
                    round(row["summary"]["avg_final_control"], 4),
                    round(row["score"], 4),
                    row["accepted"],
                ]
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--matches", type=int, default=60)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--target", type=float, default=0.5)
    parser.add_argument("--agent", choices=["heuristic", "trained_mcts"], default="trained_mcts")
    parser.add_argument("--policy", default="raspberry_blue_sim/policies/mcts_policy.json")
    parser.add_argument("--out", default="raspberry_blue_sim/balance_out")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    policy = load_policy(args.policy) if args.agent == "trained_mcts" else None
    accepted: List[Dict[str, Any]] = []
    history: List[dict] = []

    reset_balance()
    base_summary, base_aggregate = evaluate(args.matches, args.seed, args.agent, policy)
    best_score = score(base_summary, args.target)
    history.append(
        {
            "iteration": 0,
            "candidate": "baseline",
            "summary": base_summary,
            "score": best_score,
            "accepted": True,
        }
    )

    for iteration in range(1, args.iterations + 1):
        dominant_team = max(base_summary["win_rate"], key=base_summary["win_rate"].get)
        candidates = build_candidates(dominant_team, base_aggregate)
        best_candidate = None
        best_candidate_summary = None
        best_candidate_aggregate = None
        best_candidate_score = best_score

        for index, candidate in enumerate(candidates):
            reset_balance()
            apply_adjustments(accepted + [candidate])
            candidate_summary, candidate_aggregate = evaluate(
                args.matches,
                args.seed + iteration * 100 + index,
                args.agent,
                policy,
            )
            candidate_score = score(candidate_summary, args.target)
            history.append(
                {
                    "iteration": iteration,
                    "candidate": compact_adjustment(candidate),
                    "summary": candidate_summary,
                    "score": candidate_score,
                    "accepted": False,
                }
            )
            if candidate_score < best_candidate_score:
                best_candidate = candidate
                best_candidate_summary = candidate_summary
                best_candidate_aggregate = candidate_aggregate
                best_candidate_score = candidate_score

        if best_candidate is None:
            break
        accepted.append(best_candidate)
        base_summary = best_candidate_summary
        base_aggregate = best_candidate_aggregate
        best_score = best_candidate_score
        history.append(
            {
                "iteration": iteration,
                "candidate": compact_adjustment(best_candidate),
                "summary": base_summary,
                "score": best_score,
                "accepted": True,
            }
        )
        if best_score <= 0.08:
            break

    reset_balance()
    apply_adjustments(accepted)
    final_summary, _ = evaluate(args.matches, args.seed + 9999, args.agent, policy)
    result = {
        "agent": args.agent,
        "matches_per_eval": args.matches,
        "target_raspberry_win_rate": args.target,
        "accepted_adjustments": accepted,
        "final_summary": final_summary,
        "final_units": export_units(),
    }
    (out_dir / "balance_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_history(out_dir / "balance_history.csv", history)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
