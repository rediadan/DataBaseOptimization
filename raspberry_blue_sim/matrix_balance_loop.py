import argparse
import csv
import json
from pathlib import Path
from typing import Any

from balance import apply_adjustments, export_team_settings, export_units, reset_balance
from config import TEAMS
from run_experiment import build_summary, write_matches, write_rounds, write_unit_stats
from run_strategy_matrix import (
    STRATEGIES,
    agent_map,
    dominant_detected_strategy,
    load_strategy_policies,
    strategy_policy_agent_map,
    write_matrix,
)
from simulator import run_matches
from strategy_diversity import STRATEGY_TO_ROLES


STAT_ORDER = ["cost", "hp", "speed", "power", "cooldown", "range", "area"]
LOWER_IS_BETTER = {"cost", "cooldown"}
DEFAULT_RASPBERRY_STRATEGIES = [
    "tank_aoe_focus",
    "ranged_focus",
    "swarm_focus",
    "upgrade_focus",
    "mixed",
]
DEFAULT_BLUEBERRY_STRATEGIES = [
    "tank_aoe_focus",
    "ranged_focus",
    "swarm_focus",
    "suicide_aoe_focus",
    "upgrade_focus",
    "mixed",
]
AGENT_STRATEGY_ALIAS = {}


def agent_strategy(strategy: str) -> str:
    return AGENT_STRATEGY_ALIAS.get(strategy, strategy)


def log(message: str) -> None:
    print(message, flush=True)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_balance_adjustments(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("accepted_adjustments", []))


def matrix_ecology_score(rows: list[dict[str, Any]], raspberry_strategies: list[str], blueberry_strategies: list[str]) -> dict[str, Any]:
    if not rows:
        return {
            "score": 999.0,
            "avg_raspberry_win_rate": 0.0,
            "strategy_spread": 1.0,
            "avg_mirror_gap": 1.0,
            "extreme_rate": 1.0,
            "avg_control_gap": 1.0,
            "strongest_strategy": "",
            "weakest_strategy": "",
        }

    r_rates = [float(row["raspberry_win_rate"]) for row in rows]
    averages = agent_averages(rows, raspberry_strategies, blueberry_strategies)
    seen_agents = [row for row in averages if row["seen"]]
    avg_rates = [row["avg_win_rate"] for row in seen_agents]
    strongest_agent = max(seen_agents, key=lambda row: row["avg_win_rate"]) if seen_agents else None
    weakest_agent = min(seen_agents, key=lambda row: row["avg_win_rate"]) if seen_agents else None
    mirrors = [
        abs(float(row["raspberry_win_rate"]) - 0.5)
        for row in rows
        if agent_strategy(row["raspberry_strategy"]) == agent_strategy(row["blueberry_strategy"])
    ]
    control_gaps = [min(1.0, abs(float(row.get("avg_final_control", 0.0))) / 3.0) for row in rows]
    extreme_rate = sum(1 for value in r_rates if value <= 0.05 or value >= 0.95) / len(r_rates)
    avg_r = average(r_rates)
    strategy_spread = max(avg_rates) - min(avg_rates) if avg_rates else 1.0
    avg_mirror_gap = average(mirrors) if mirrors else 0.0
    avg_control_gap = average(control_gaps)
    score = (
        abs(avg_r - 0.5) * 0.16
        + strategy_spread * 0.30
        + avg_mirror_gap * 0.22
        + extreme_rate * 0.24
        + avg_control_gap * 0.08
    )
    return {
        "score": round(score, 6),
        "avg_raspberry_win_rate": round(avg_r, 4),
        "strategy_spread": round(strategy_spread, 4),
        "avg_mirror_gap": round(avg_mirror_gap, 4),
        "extreme_rate": round(extreme_rate, 4),
        "avg_control_gap": round(avg_control_gap, 4),
        "strongest_team": strongest_agent["team"] if strongest_agent else "",
        "strongest_strategy": strongest_agent["strategy"] if strongest_agent else "",
        "strongest_strategy_avg": round(strongest_agent["avg_win_rate"], 4) if strongest_agent else 0.0,
        "weakest_team": weakest_agent["team"] if weakest_agent else "",
        "weakest_strategy": weakest_agent["strategy"] if weakest_agent else "",
        "weakest_strategy_avg": round(weakest_agent["avg_win_rate"], 4) if weakest_agent else 0.0,
    }


def agent_averages(
    rows: list[dict[str, Any]],
    raspberry_strategies: list[str],
    blueberry_strategies: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for strategy in raspberry_strategies:
        values = [
            float(row["raspberry_win_rate"])
            for row in rows
            if row["raspberry_strategy"] == strategy
        ]
        avg = average(values) if values else 0.0
        result.append(
            {
                "team": "raspberry",
                "strategy": strategy,
                "avg_win_rate": round(avg, 4),
                "as_raspberry": round(avg, 4) if values else "",
                "as_blueberry": "",
                "combined": round(avg, 4),
                "seen": bool(values),
                "samples": len(values),
            }
        )
    for strategy in blueberry_strategies:
        values = [
            float(row["blueberry_win_rate"])
            for row in rows
            if row["blueberry_strategy"] == strategy
        ]
        avg = average(values) if values else 0.0
        result.append(
            {
                "team": "blueberry",
                "strategy": strategy,
                "avg_win_rate": round(avg, 4),
                "as_raspberry": "",
                "as_blueberry": round(avg, 4) if values else "",
                "combined": round(avg, 4),
                "seen": bool(values),
                "samples": len(values),
            }
        )
    return result


def average(values: list[float]) -> float:
    clean = [value for value in values if isinstance(value, (int, float))]
    return sum(clean) / len(clean) if clean else 0.0


def write_strategy_averages(path: Path, rows: list[dict[str, Any]], raspberry_strategies: list[str], blueberry_strategies: list[str]) -> None:
    averages = agent_averages(rows, raspberry_strategies, blueberry_strategies)
    write_rows(
        path,
        ["team", "strategy", "avg_win_rate", "as_raspberry", "as_blueberry", "combined", "samples"],
        [
            {
                "team": row["team"],
                "strategy": row["strategy"],
                "avg_win_rate": row["avg_win_rate"],
                "as_raspberry": row["as_raspberry"],
                "as_blueberry": row["as_blueberry"],
                "combined": row["combined"],
                "samples": row["samples"],
            }
            for row in averages
        ],
    )


def write_loop_matrix_report(
    path: Path,
    matches: int,
    raspberry_strategies: list[str],
    blueberry_strategies: list[str],
    rows: list[dict[str, Any]],
    agent_mode: str,
    mcts_iterations: int,
    policy_dir: str,
    live: bool = False,
) -> None:
    total = len(raspberry_strategies) * len(blueberry_strategies)
    report = {
        "matches_per_matchup": matches,
        "raspberry_strategies": raspberry_strategies,
        "blueberry_strategies": blueberry_strategies,
        "agent_mode": agent_mode,
        "mcts_iterations": mcts_iterations,
        "policy_dir": policy_dir.replace("\\", "/") if policy_dir else "",
        "score": matrix_ecology_score(rows, raspberry_strategies, blueberry_strategies),
        "rows": rows,
    }
    if live:
        report["live"] = True
        report["completed_matchups"] = len(rows)
        report["total_matchups"] = total
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(out_dir: Path, payload: dict[str, Any]) -> None:
    (out_dir / "loop_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_full_matrix(
    out_dir: Path,
    iteration_dir: Path,
    iteration: int,
    total_iterations: int,
    raspberry_strategies: list[str],
    blueberry_strategies: list[str],
    matches: int,
    seed: int,
    agent_mode: str,
    mcts_iterations: int,
    policy_dir: str,
    policy_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_matchups = len(raspberry_strategies) * len(blueberry_strategies)
    for r_index, raspberry_strategy in enumerate(raspberry_strategies):
        for b_index, blueberry_strategy in enumerate(blueberry_strategies):
            completed = len(rows)
            matchup_name = f"{raspberry_strategy}_vs_{blueberry_strategy}"
            matchup_dir = iteration_dir / matchup_name
            matchup_dir.mkdir(parents=True, exist_ok=True)
            write_status(
                out_dir,
                {
                    "status": "running",
                    "phase": "matrix",
                    "iteration": iteration,
                    "total_iterations": total_iterations,
                    "completed_matchups": completed,
                    "total_matchups": total_matchups,
                    "current_matchup": f"{raspberry_strategy} vs {blueberry_strategy}",
                    "matrix_csv": "current_matrix.csv",
                    "strategy_averages_csv": "current_strategy_averages.csv",
                    "raspberry_strategies": raspberry_strategies,
                    "blueberry_strategies": blueberry_strategies,
                },
            )
            matchup_seed = seed + iteration * 100000 + r_index * 1000 + b_index * 37
            r_agent_strategy = agent_strategy(raspberry_strategy)
            b_agent_strategy = agent_strategy(blueberry_strategy)
            if agent_mode == "strategy_policy":
                matchup_agent = strategy_policy_agent_map(r_agent_strategy, b_agent_strategy)
                matchup_policy = {
                    "raspberry": policy_cache[r_agent_strategy].get("raspberry", {}),
                    "blueberry": policy_cache[b_agent_strategy].get("blueberry", {}),
                }
            else:
                matchup_agent = agent_map(r_agent_strategy, b_agent_strategy, agent_mode, mcts_iterations)
                matchup_policy = None
            progress_label = f"iteration {iteration}/{total_iterations} {raspberry_strategy} vs {blueberry_strategy}"
            match_rows, round_rows, aggregate = run_matches(
                matches,
                matchup_seed,
                matchup_agent,
                matchup_policy,
                progress_label=progress_label,
                progress_updates=2,
            )
            write_matches(matchup_dir / "matches.csv", match_rows)
            write_rounds(matchup_dir / "rounds.csv", round_rows)
            write_unit_stats(matchup_dir / "unit_stats.csv", aggregate, matches)
            summary = build_summary(
                match_rows,
                round_rows,
                aggregate,
                matches,
                f"matrix_balance_loop:{iteration}:{matchup_name}",
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
            write_matrix(iteration_dir / "strategy_matrix.csv", rows)
            write_matrix(out_dir / "current_matrix.csv", rows)
            write_loop_matrix_report(
                iteration_dir / "strategy_matrix_summary.json",
                matches,
                raspberry_strategies,
                blueberry_strategies,
                rows,
                agent_mode,
                mcts_iterations,
                policy_dir,
                live=len(rows) < total_matchups,
            )
            write_loop_matrix_report(
                out_dir / "current_matrix_summary.json",
                matches,
                raspberry_strategies,
                blueberry_strategies,
                rows,
                agent_mode,
                mcts_iterations,
                policy_dir,
                live=len(rows) < total_matchups,
            )
            write_strategy_averages(iteration_dir / "strategy_averages.csv", rows, raspberry_strategies, blueberry_strategies)
            write_strategy_averages(out_dir / "current_strategy_averages.csv", rows, raspberry_strategies, blueberry_strategies)
            log(json.dumps({"iteration": iteration, **row}, ensure_ascii=False))
    return rows


def build_strategy_patch(
    iteration: int,
    rows: list[dict[str, Any]],
    raspberry_strategies: list[str],
    blueberry_strategies: list[str],
    strength: float,
    min_gap: float,
    weak_count: int,
    previous_candidates: list[dict[str, Any]] | None = None,
    target_confirmations: int = 2,
) -> dict[str, Any]:
    averages = [row for row in agent_averages(rows, raspberry_strategies, blueberry_strategies) if row["seen"]]
    if len(averages) < 2:
        return {
            "iteration": iteration,
            "applied": False,
            "reason": "not enough matrix data for strategy patch",
            "strategy_spread": 0.0,
            "candidate_targets": [],
            "confirmed_targets": [],
            "targets": [],
            "adjustments": [],
        }
    sorted_agents = sorted(averages, key=lambda row: row["avg_win_rate"])
    weakest_agents = sorted_agents[: max(1, weak_count)]
    strongest_agent = sorted_agents[-1]
    spread = strongest_agent["avg_win_rate"] - weakest_agents[0]["avg_win_rate"]
    adjustments: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []

    if spread < min_gap:
        return {
            "iteration": iteration,
            "applied": False,
            "reason": f"strategy spread {spread:.4f} is below min gap {min_gap:.4f}",
            "strategy_spread": round(spread, 4),
            "candidate_targets": [],
            "confirmed_targets": [],
            "targets": [],
            "adjustments": [],
        }

    candidate_agents = [{"team": strongest_agent["team"], "strategy": strongest_agent["strategy"], "mode": "nerf", "avg_win_rate": strongest_agent["avg_win_rate"]}]
    for weak in weakest_agents:
        if weak["team"] == strongest_agent["team"] and weak["strategy"] == strongest_agent["strategy"]:
            continue
        candidate_agents.append({"team": weak["team"], "strategy": weak["strategy"], "mode": "buff", "avg_win_rate": weak["avg_win_rate"]})

    previous_keys = {target_key(target) for target in previous_candidates or []}
    confirmed_agents = [
        candidate
        for candidate in candidate_agents
        if target_confirmations <= 1 or target_key(candidate) in previous_keys
    ]
    if not confirmed_agents:
        return {
            "iteration": iteration,
            "applied": False,
            "reason": f"waiting for repeated strong/weak targets ({len(candidate_agents)} candidates)",
            "strategy_spread": round(spread, 4),
            "candidate_targets": candidate_agents,
            "confirmed_targets": [],
            "targets": [],
            "adjustments": [],
        }

    for target in confirmed_agents:
        team = target["team"]
        strategy = target["strategy"]
        mode = target["mode"]
        avg = target["avg_win_rate"]
        distance = abs(avg - 0.5)
        scaled_strength = max(0.012, min(strength, strength * (0.55 + distance * 1.8)))
        targets.append(
            {
                "team": team,
                "strategy": strategy,
                "mode": mode,
                "avg_win_rate": round(avg, 4),
                "strength": round(scaled_strength, 4),
            }
        )
        adjustments.extend(strategy_adjustments(team, strategy, mode, scaled_strength, iteration))

    return {
        "iteration": iteration,
        "applied": True,
        "reason": ", ".join(f"{target['mode']} {target['team']} {target['strategy']}" for target in targets),
        "strategy_spread": round(spread, 4),
        "candidate_targets": candidate_agents,
        "confirmed_targets": confirmed_agents,
        "targets": targets,
        "adjustments": adjustments,
    }


def target_key(target: dict[str, Any]) -> tuple[str, str, str]:
    return (str(target.get("team", "")), str(target.get("strategy", "")), str(target.get("mode", "")))


def strategy_adjustments(team: str, strategy: str, mode: str, strength: float, iteration: int) -> list[dict[str, Any]]:
    adjustments = []
    if strategy == "upgrade_focus":
        adjustments.extend(upgrade_system_adjustments(team, mode, strength, iteration))
    for unit_key in strategy_units(team, strategy):
        for stat, weight in stat_profile(team, unit_key, strategy, mode):
            factor = factor_for(stat, mode, strength * weight)
            adjustments.append(
                {
                    "iteration": iteration,
                    "team": team,
                    "unit": unit_key,
                    "stat": stat,
                    "factor": round(factor, 4),
                    "mode": mode,
                    "strategy": strategy,
                    "reason": f"{mode} {strategy}",
                }
            )
    return adjustments


def upgrade_system_adjustments(team: str, mode: str, strength: float, iteration: int) -> list[dict[str, Any]]:
    if mode == "nerf":
        cost_factor = 1.0 + strength * 0.85
        rate_factor = 1.0 / (1.0 + strength * 0.55)
    else:
        cost_factor = 1.0 / (1.0 + strength * 0.65)
        rate_factor = 1.0 + strength * 0.35
    return [
        {
            "iteration": iteration,
            "team": team,
            "unit": "__upgrade__",
            "stat": "upgrade_cost_factor",
            "factor": round(cost_factor, 4),
            "mode": mode,
            "strategy": "upgrade_focus",
            "reason": f"{mode} upgrade economy",
        },
        {
            "iteration": iteration,
            "team": team,
            "unit": "__upgrade__",
            "stat": "upgrade_rate_factor",
            "factor": round(rate_factor, 4),
            "mode": mode,
            "strategy": "upgrade_focus",
            "reason": f"{mode} upgrade efficiency",
        },
    ]


def strategy_units(team: str, strategy: str) -> list[str]:
    role_map = {key: set(value) for key, value in STRATEGY_TO_ROLES.items()}
    role_map["mixed"] = {spec.role for spec in TEAMS[team]["units"]}
    role_map["upgrade_focus"] = {"attacker", "tank", "single_ranged"}
    role_map["healer_support"] = {"special", "tank"}
    role_map["suicide_aoe_focus"] = {"special"}
    roles = role_map.get(strategy, role_map["mixed"])
    return [spec.key for spec in TEAMS[team]["units"] if spec.role in roles]


def stat_profile(team: str, unit_key: str, strategy: str, mode: str) -> list[tuple[str, float]]:
    spec = next(spec for spec in TEAMS[team]["units"] if spec.key == unit_key)
    if mode == "nerf":
        profiles = {
            "tank_focus": [("hp", 0.75), ("cost", 0.55), ("speed", 0.30)],
            "tank_aoe_focus": [("hp", 0.55), ("area", 0.45), ("range", 0.35), ("cost", 0.35)],
            "ranged_focus": [("range", 0.65), ("power", 0.50), ("cooldown", 0.45), ("cost", 0.35)],
            "swarm_focus": [("cost", 0.70), ("cooldown", 0.45), ("speed", 0.35)],
            "special_focus": [("area", 0.65), ("power", 0.50), ("cooldown", 0.35), ("cost", 0.30)],
            "healer_support": [("hp", 0.45), ("power", 0.40), ("cooldown", 0.35), ("cost", 0.30)],
            "suicide_aoe_focus": [("area", 0.75), ("power", 0.55), ("speed", 0.30), ("cost", 0.30)],
            "upgrade_focus": [("cost", 0.60), ("hp", 0.35), ("power", 0.35), ("cooldown", 0.30)],
            "mixed": [("cost", 0.35), ("hp", 0.30), ("power", 0.30)],
        }
        return valid_stats(spec, profiles.get(strategy, profiles["mixed"]))

    profiles = {
        "tank_focus": [("hp", 1.00), ("cost", 0.55), ("speed", 0.25), ("power", -0.22)],
        "tank_aoe_focus": [("hp", 0.65), ("area", 0.70), ("range", 0.35), ("cost", 0.25), ("power", -0.12)],
        "ranged_focus": [("range", 0.85), ("power", 0.55), ("cooldown", 0.45), ("cost", -0.20)],
        "swarm_focus": [("cost", 0.90), ("cooldown", 0.60), ("speed", 0.35), ("hp", -0.18)],
        "special_focus": [("area", 0.85), ("range", 0.40), ("cooldown", 0.50), ("power", 0.40), ("hp", -0.18)],
        "healer_support": [("hp", 0.75), ("power", 0.65), ("cooldown", 0.45), ("cost", 0.30)],
        "suicide_aoe_focus": [("area", 0.95), ("power", 0.70), ("speed", 0.35), ("cooldown", 0.30), ("hp", -0.20)],
        "upgrade_focus": [("cost", 0.55), ("cooldown", 0.30), ("hp", 0.22), ("power", 0.22)],
        "mixed": [("cost", 0.25), ("hp", 0.22), ("power", 0.22), ("speed", 0.16)],
    }
    return valid_stats(spec, profiles.get(strategy, profiles["mixed"]))


def valid_stats(spec: Any, stats: list[tuple[str, float]]) -> list[tuple[str, float]]:
    result = []
    for stat, weight in stats:
        if stat not in STAT_ORDER:
            continue
        if stat in {"power", "range", "area"} and getattr(spec, stat) <= 0:
            continue
        result.append((stat, weight))
    return result


def factor_for(stat: str, mode: str, amount: float) -> float:
    if amount < 0:
        return factor_for(stat, "nerf" if mode == "buff" else "buff", abs(amount))
    if stat in LOWER_IS_BETTER:
        return 1.0 + amount if mode == "nerf" else 1.0 / (1.0 + amount)
    return 1.0 / (1.0 + amount) if mode == "nerf" else 1.0 + amount


def write_patch_files(out_dir: Path, patch: dict[str, Any], accepted_adjustments: list[dict[str, Any]]) -> None:
    (out_dir / "current_patch.json").write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")
    write_rows(
        out_dir / "current_patch_adjustments.csv",
        ["iteration", "team", "unit", "stat", "factor", "mode", "strategy", "reason"],
        patch.get("adjustments", []),
    )
    (out_dir / "current_adjustments.json").write_text(
        json.dumps(
            {
                "accepted_adjustments": accepted_adjustments,
                "final_units": export_units(),
                "team_settings": export_team_settings(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def append_iteration_history(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any], patch: dict[str, Any]) -> None:
    existing = []
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    existing.append(
        {
            "iteration": patch["iteration"],
            "score": summary["score"],
            "avg_raspberry_win_rate": summary["avg_raspberry_win_rate"],
            "strategy_spread": summary["strategy_spread"],
            "avg_mirror_gap": summary["avg_mirror_gap"],
            "extreme_rate": summary["extreme_rate"],
            "avg_control_gap": summary["avg_control_gap"],
            "strongest_team": summary["strongest_team"],
            "strongest_strategy": summary["strongest_strategy"],
            "strongest_strategy_avg": summary["strongest_strategy_avg"],
            "weakest_team": summary["weakest_team"],
            "weakest_strategy": summary["weakest_strategy"],
            "weakest_strategy_avg": summary["weakest_strategy_avg"],
            "patch_applied": patch["applied"],
            "patch_reason": patch["reason"],
        }
    )
    write_rows(
        path,
        [
            "iteration",
            "score",
            "avg_raspberry_win_rate",
            "strategy_spread",
            "avg_mirror_gap",
            "extreme_rate",
            "avg_control_gap",
            "strongest_team",
            "strongest_strategy",
            "strongest_strategy_avg",
            "weakest_team",
            "weakest_strategy",
            "weakest_strategy_avg",
            "patch_applied",
            "patch_reason",
        ],
        existing,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="raspberry_blue_sim/live_matrix_balance_loop_current")
    parser.add_argument("--base-balance-result", default="")
    parser.add_argument("--policy-dir", default="")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--matches", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument("--patch-strength", type=float, default=0.055)
    parser.add_argument("--min-strategy-gap", type=float, default=0.08)
    parser.add_argument("--weak-count", type=int, default=2)
    parser.add_argument("--target-confirmations", type=int, default=2)
    parser.add_argument("--agent-mode", choices=["strategy_policy", "strategy_mcts", "strategy_biased"], default="strategy_policy")
    parser.add_argument("--mcts-iterations", type=int, default=4)
    parser.add_argument("--strategies", nargs="*", default=None)
    parser.add_argument("--raspberry-strategies", nargs="*", default=DEFAULT_RASPBERRY_STRATEGIES)
    parser.add_argument("--blueberry-strategies", nargs="*", default=DEFAULT_BLUEBERRY_STRATEGIES)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted_adjustments = read_balance_adjustments(args.base_balance_result)
    raspberry_strategies = args.strategies or args.raspberry_strategies
    blueberry_strategies = args.strategies or args.blueberry_strategies
    policy_strategies = sorted({agent_strategy(strategy) for strategy in raspberry_strategies + blueberry_strategies})
    policy_cache = load_strategy_policies(args.policy_dir, policy_strategies) if args.agent_mode == "strategy_policy" else {}

    write_status(
        out_dir,
        {
            "status": "starting",
            "phase": "setup",
            "iteration": 0,
            "total_iterations": args.iterations,
            "completed_matchups": 0,
            "total_matchups": len(raspberry_strategies) * len(blueberry_strategies),
            "raspberry_strategies": raspberry_strategies,
            "blueberry_strategies": blueberry_strategies,
        },
    )
    log(
        f"[matrix-balance-loop start] iterations={args.iterations}, matches={args.matches}, "
        f"agent_mode={args.agent_mode}, patch_strength={args.patch_strength}, "
        f"weak_count={args.weak_count}, target_confirmations={args.target_confirmations}"
    )

    all_iteration_summaries = []
    patch_history = []
    previous_patch_candidates: list[dict[str, Any]] = []
    for iteration in range(1, args.iterations + 1):
        reset_balance()
        apply_adjustments(accepted_adjustments)
        iteration_dir = out_dir / f"iteration_{iteration:02d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        log(f"[iteration {iteration}/{args.iterations}] matrix start")
        rows = run_full_matrix(
            out_dir,
            iteration_dir,
            iteration,
            args.iterations,
            raspberry_strategies,
            blueberry_strategies,
            args.matches,
            args.seed,
            args.agent_mode,
            args.mcts_iterations,
            args.policy_dir,
            policy_cache,
        )
        summary = matrix_ecology_score(rows, raspberry_strategies, blueberry_strategies)
        all_iteration_summaries.append({"iteration": iteration, **summary})
        (iteration_dir / "matrix_ecology_score.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"[iteration {iteration}/{args.iterations}] matrix done: {json.dumps(summary, ensure_ascii=False)}")

        if iteration < args.iterations:
            patch = build_strategy_patch(
                iteration,
                rows,
                raspberry_strategies,
                blueberry_strategies,
                args.patch_strength,
                args.min_strategy_gap,
                args.weak_count,
                previous_patch_candidates,
                args.target_confirmations,
            )
            previous_patch_candidates = patch.get("candidate_targets", [])
            if patch["applied"]:
                accepted_adjustments.extend(patch["adjustments"])
            patch_history.append(patch)
            reset_balance()
            apply_adjustments(accepted_adjustments)
            write_patch_files(out_dir, patch, accepted_adjustments)
            append_iteration_history(out_dir / "iteration_history.csv", rows, summary, patch)
            write_status(
                out_dir,
                {
                    "status": "running",
                    "phase": "patch",
                    "iteration": iteration,
                    "total_iterations": args.iterations,
                    "completed_matchups": len(raspberry_strategies) * len(blueberry_strategies),
                    "total_matchups": len(raspberry_strategies) * len(blueberry_strategies),
                    "raspberry_strategies": raspberry_strategies,
                    "blueberry_strategies": blueberry_strategies,
                    "latest_score": summary,
                    "latest_patch": patch,
                },
            )
            log(f"[iteration {iteration}/{args.iterations}] patch: {json.dumps(patch, ensure_ascii=False)}")
        else:
            patch = {
                "iteration": iteration,
                "applied": False,
                "reason": "final validation iteration; no unvalidated patch applied",
                "strategy_spread": summary["strategy_spread"],
                "targets": [],
                "adjustments": [],
            }
            append_iteration_history(out_dir / "iteration_history.csv", rows, summary, patch)

    final_result = {
        "mode": "matrix_balance_loop",
        "iterations": args.iterations,
        "matches": args.matches,
        "agent_mode": args.agent_mode,
        "mcts_iterations": args.mcts_iterations,
        "raspberry_strategies": raspberry_strategies,
        "blueberry_strategies": blueberry_strategies,
        "policy_dir": args.policy_dir.replace("\\", "/"),
        "base_balance_result": args.base_balance_result.replace("\\", "/"),
        "patch_strength": args.patch_strength,
        "min_strategy_gap": args.min_strategy_gap,
        "weak_count": args.weak_count,
        "target_confirmations": args.target_confirmations,
        "iteration_summaries": all_iteration_summaries,
        "patch_history": patch_history,
        "accepted_adjustments": accepted_adjustments,
        "final_units": export_units(),
        "team_settings": export_team_settings(),
    }
    (out_dir / "final_result.json").write_text(json.dumps(final_result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_status(
        out_dir,
        {
            "status": "finished",
            "phase": "done",
            "iteration": args.iterations,
            "total_iterations": args.iterations,
            "completed_matchups": len(raspberry_strategies) * len(blueberry_strategies),
            "total_matchups": len(raspberry_strategies) * len(blueberry_strategies),
            "raspberry_strategies": raspberry_strategies,
            "blueberry_strategies": blueberry_strategies,
            "latest_score": all_iteration_summaries[-1] if all_iteration_summaries else {},
            "final_result": "final_result.json",
        },
    )
    log(f"[matrix-balance-loop finished] wrote: {out_dir}")


if __name__ == "__main__":
    main()
