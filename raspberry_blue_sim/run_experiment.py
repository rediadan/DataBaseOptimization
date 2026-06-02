import argparse
import csv
import json
from pathlib import Path

from balance import apply_adjustments, reset_balance
from config import TEAMS
from simulator import load_policy, run_matches
from strategy_diversity import summarize_strategy_diversity


def write_matches(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "match_id",
                "winner",
                "raspberry_rounds",
                "blueberry_rounds",
                "rounds_played",
                "raspberry_final_upgrades",
                "blueberry_final_upgrades",
                "raspberry_strategy",
                "blueberry_strategy",
            ]
        )
        for row in rows:
            raspberry_profile = getattr(row, "strategy_by_team", {}).get("raspberry", {})
            blueberry_profile = getattr(row, "strategy_by_team", {}).get("blueberry", {})
            writer.writerow(
                [
                    row.match_id,
                    row.winner,
                    row.raspberry_rounds,
                    row.blueberry_rounds,
                    row.rounds_played,
                    row.raspberry_final_upgrades,
                    row.blueberry_final_upgrades,
                    raspberry_profile.get("strategy", ""),
                    blueberry_profile.get("strategy", ""),
                ]
            )


def write_rounds(path: Path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "match_id",
                "round_no",
                "winner",
                "duration",
                "final_control",
                "raspberry_upgrades",
                "blueberry_upgrades",
                "reason",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.match_id,
                    row.round_no,
                    row.winner,
                    row.duration,
                    row.final_control,
                    row.raspberry_upgrades,
                    row.blueberry_upgrades,
                    row.reason,
                ]
            )


def write_unit_stats(path: Path, aggregate, matches: int):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "team",
                "unit_key",
                "unit_name",
                "produced",
                "produced_per_match",
                "team_production_share",
                "kills",
                "kills_per_match",
                "deaths",
                "damage",
                "damage_per_match",
                "damage_taken",
                "healing",
                "attacks_made",
                "attacks_received",
                "survival_time",
                "avg_survival_time",
                "focus_fire_hits",
                "focus_fire_events",
                "max_focus_attackers",
            ]
        )
        for team, state in aggregate.items():
            specs = {spec.key: spec for spec in TEAMS[team]["units"]}
            keys = sorted(
                set(state.produced)
                | set(state.kills)
                | set(state.damage)
                | set(state.healing)
                | set(state.deaths)
                | set(state.damage_taken)
                | set(state.attacks_made)
                | set(state.attacks_received)
                | set(state.survival_time)
                | set(state.focus_fire_hits)
                | set(state.focus_fire_events)
                | set(state.max_focus_attackers)
            )
            team_total_produced = sum(state.produced.values()) or 1
            for key in keys:
                produced = state.produced.get(key, 0)
                survival_time = state.survival_time.get(key, 0.0)
                writer.writerow(
                    [
                        team,
                        key,
                        specs[key].name,
                        produced,
                        round(produced / matches, 4),
                        round(produced / team_total_produced, 4),
                        state.kills.get(key, 0),
                        round(state.kills.get(key, 0) / matches, 4),
                        state.deaths.get(key, 0),
                        round(state.damage.get(key, 0.0), 2),
                        round(state.damage.get(key, 0.0) / matches, 4),
                        round(state.damage_taken.get(key, 0.0), 2),
                        round(state.healing.get(key, 0.0), 2),
                        state.attacks_made.get(key, 0),
                        state.attacks_received.get(key, 0),
                        round(survival_time, 2),
                        round(survival_time / produced, 4) if produced else 0.0,
                        state.focus_fire_hits.get(key, 0),
                        state.focus_fire_events.get(key, 0),
                        state.max_focus_attackers.get(key, 0),
                    ]
                )


def build_summary(match_rows, round_rows, aggregate, matches: int, agent_type: str):
    wins = {team: sum(1 for row in match_rows if row.winner == team) for team in TEAMS}
    round_wins = {team: sum(1 for row in round_rows if row.winner == team) for team in TEAMS}
    avg_control = sum(row.final_control for row in round_rows) / len(round_rows) if round_rows else 0.0
    avg_duration = sum(row.duration for row in round_rows) / len(round_rows) if round_rows else 0.0
    return {
        "matches": matches,
        "agent_type": agent_type,
        "match_wins": wins,
        "match_win_rate": {team: round(wins[team] / matches, 4) for team in TEAMS},
        "round_wins": round_wins,
        "rounds_played": len(round_rows),
        "avg_final_control": round(avg_control, 4),
        "avg_round_duration": round(avg_duration, 4),
        "avg_final_upgrades_per_match": {
            team: round(aggregate[team].upgrade_level / matches, 4) for team in TEAMS
        },
        "avg_final_attack_upgrades_per_match": {
            team: round(aggregate[team].attack_upgrade_level / matches, 4) for team in TEAMS
        },
        "avg_final_hp_upgrades_per_match": {
            team: round(aggregate[team].hp_upgrade_level / matches, 4) for team in TEAMS
        },
        "strategy_diversity": summarize_strategy_diversity(match_rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agent", choices=["heuristic", "mcts", "trained_mcts"], default="heuristic")
    parser.add_argument("--policy", default="")
    parser.add_argument("--balance-result", default="")
    parser.add_argument("--out", default="raspberry_blue_sim/out")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.balance_result:
        reset_balance()
        balance_result = json.loads(Path(args.balance_result).read_text(encoding="utf-8"))
        apply_adjustments(balance_result.get("accepted_adjustments", []))

    policy = load_policy(args.policy) if args.agent == "trained_mcts" else None
    match_rows, round_rows, aggregate = run_matches(args.matches, args.seed, args.agent, policy)
    write_matches(out_dir / "matches.csv", match_rows)
    write_rounds(out_dir / "rounds.csv", round_rows)
    write_unit_stats(out_dir / "unit_stats.csv", aggregate, args.matches)

    summary = build_summary(match_rows, round_rows, aggregate, args.matches, args.agent)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
