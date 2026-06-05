import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from balance import apply_adjustments, export_units, reset_balance
from config import TEAMS
from run_experiment import build_summary, write_matches, write_rounds, write_unit_stats
from run_strategy_matrix import (
    STRATEGIES,
    combined_strategy_policy,
    dominant_detected_strategy,
    load_strategy_policies,
    strategy_policy_agent_map,
    write_matrix,
    write_matrix_report,
)
from simulator import run_matches
from strategy_diversity import STRATEGY_TO_ROLES


STAT_ORDER = ["cost", "hp", "speed", "power", "cooldown", "range", "area"]
LOWER_IS_BETTER = {"cost", "cooldown"}


def log(message: str) -> None:
    print(message, flush=True)


def read_balance_result(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("accepted_adjustments", []))


def read_matrix_csv(path: str) -> list[dict[str, Any]]:
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append(
                {
                    **row,
                    "raspberry_win_rate": float(row["raspberry_win_rate"]),
                    "blueberry_win_rate": float(row["blueberry_win_rate"]),
                    "avg_final_control": float(row["avg_final_control"]),
                    "avg_round_duration": float(row["avg_round_duration"]),
                    "strategy_diversity_penalty": float(row["strategy_diversity_penalty"]),
                }
            )
    return rows


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def strategy_rates(rows: list[dict[str, Any]], strategies: list[str]) -> dict[str, dict[str, float]]:
    result = {}
    for strategy in strategies:
        as_raspberry = [row["raspberry_win_rate"] for row in rows if row["raspberry_strategy"] == strategy]
        as_blueberry = [row["blueberry_win_rate"] for row in rows if row["blueberry_strategy"] == strategy]
        combined = as_raspberry + as_blueberry
        result[strategy] = {
            "as_raspberry": average(as_raspberry),
            "as_blueberry": average(as_blueberry),
            "combined": average(combined),
        }
    return result


def average(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    return sum(clean) / len(clean) if clean else 0.0


def select_problem_matchups(rows: list[dict[str, Any]], strategies: list[str], limit: int) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}

    def add(row: dict[str, Any]) -> None:
        selected[(row["raspberry_strategy"], row["blueberry_strategy"])] = row

    mirrors = [
        row
        for row in rows
        if row["raspberry_strategy"] == row["blueberry_strategy"]
    ]
    for row in sorted(mirrors, key=lambda item: abs(item["raspberry_win_rate"] - 0.5), reverse=True)[: max(2, limit // 3)]:
        add(row)

    extreme_rows = sorted(rows, key=cell_severity, reverse=True)
    for row in extreme_rows:
        add(row)
        if len(selected) >= limit:
            break

    rates = strategy_rates(rows, strategies)
    weakest = sorted(strategies, key=lambda strategy: rates[strategy]["combined"])[:2]
    strongest = sorted(strategies, key=lambda strategy: rates[strategy]["combined"], reverse=True)[:2]
    for strategy in weakest + strongest:
        strategy_rows = [
            row
            for row in rows
            if row["raspberry_strategy"] == strategy or row["blueberry_strategy"] == strategy
        ]
        for row in sorted(strategy_rows, key=cell_severity, reverse=True)[:2]:
            add(row)
            if len(selected) >= limit:
                break
        if len(selected) >= limit:
            break

    return list(selected.values())[:limit]


def cell_severity(row: dict[str, Any]) -> float:
    rate_gap = abs(float(row["raspberry_win_rate"]) - 0.5) * 2.0
    control_gap = min(1.0, abs(float(row.get("avg_final_control", 0.0))) / 3.0)
    diversity = float(row.get("strategy_diversity_penalty", 0.0))
    return rate_gap * 0.72 + control_gap * 0.18 + diversity * 0.10


def build_candidate_patches(
    matrix_rows: list[dict[str, Any]],
    strategies: list[str],
    strength: float,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str, str, float], ...]] = set()
    rates = strategy_rates(matrix_rows, strategies)
    weakest = sorted(strategies, key=lambda strategy: rates[strategy]["combined"])[:2]
    strongest = sorted(strategies, key=lambda strategy: rates[strategy]["combined"], reverse=True)[:2]

    def add(candidate: dict[str, Any]) -> None:
        key = tuple(
            sorted(
                (
                    item["team"],
                    item["unit"],
                    item["stat"],
                    round(float(item.get("factor", 1.0)), 4),
                )
                for item in candidate["adjustments"]
            )
        )
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    for strategy in strongest:
        for team in ("raspberry", "blueberry"):
            add(strategy_patch(team, strategy, "nerf", strength, f"nerf strong {team} {strategy}"))

    for strategy in weakest:
        for team in ("raspberry", "blueberry"):
            add(strategy_patch(team, strategy, "buff", strength, f"buff weak {team} {strategy}"))

    for row in sorted(matrix_rows, key=cell_severity, reverse=True)[: max(6, limit)]:
        r_strategy = row["raspberry_strategy"]
        b_strategy = row["blueberry_strategy"]
        r_rate = row["raspberry_win_rate"]
        if r_rate >= 0.62:
            add(
                combined_patch(
                    [
                        strategy_patch("raspberry", r_strategy, "nerf", strength * 0.75, f"cell nerf raspberry {r_strategy}"),
                        strategy_patch("blueberry", b_strategy, "buff", strength * 0.75, f"cell buff blueberry {b_strategy}"),
                    ],
                    f"soften R-favored {r_strategy} vs {b_strategy}",
                )
            )
        elif r_rate <= 0.38:
            add(
                combined_patch(
                    [
                        strategy_patch("blueberry", b_strategy, "nerf", strength * 0.75, f"cell nerf blueberry {b_strategy}"),
                        strategy_patch("raspberry", r_strategy, "buff", strength * 0.75, f"cell buff raspberry {r_strategy}"),
                    ],
                    f"soften B-favored {r_strategy} vs {b_strategy}",
                )
            )
        if len(candidates) >= limit:
            break

    return candidates[:limit]


def combined_patch(parts: list[dict[str, Any]], description: str) -> dict[str, Any]:
    adjustments = []
    for part in parts:
        adjustments.extend(part["adjustments"])
    return {
        "kind": "matrix_cell_rebalance",
        "description": description,
        "adjustments": adjustments,
    }


def strategy_patch(team: str, strategy: str, mode: str, strength: float, description: str) -> dict[str, Any]:
    units = strategy_units(team, strategy)
    adjustments = []
    for unit_key in units:
        for stat, weight in stat_profile(team, unit_key, strategy, mode):
            factor = factor_for(stat, mode, strength * weight)
            adjustments.append(
                {
                    "team": team,
                    "unit": unit_key,
                    "stat": stat,
                    "factor": round(factor, 4),
                    "reason": description,
                }
            )
    return {
        "kind": f"matrix_strategy_{mode}",
        "description": description,
        "team": team,
        "strategy": strategy,
        "mode": mode,
        "adjustments": adjustments,
    }


def strategy_units(team: str, strategy: str) -> list[str]:
    role_map = STRATEGY_TO_ROLES.copy()
    role_map["mixed"] = {spec.role for spec in TEAMS[team]["units"]}
    role_map["mixed_composition"] = role_map["mixed"]
    role_map["upgrade_focus"] = {spec.role for spec in TEAMS[team]["units"] if spec.role in {"attacker", "tank", "single_ranged"}}
    roles = role_map.get(strategy, role_map["mixed"])
    units = [spec.key for spec in TEAMS[team]["units"] if spec.role in roles]
    return units[:3]


def stat_profile(team: str, unit_key: str, strategy: str, mode: str) -> list[tuple[str, float]]:
    spec = next(spec for spec in TEAMS[team]["units"] if spec.key == unit_key)
    if strategy == "upgrade_focus":
        return [("cost", 0.8), ("hp", 0.45), ("power", 0.45), ("cooldown", 0.35)]
    stats = [("cost", 0.85), ("hp", 0.60), ("speed", 0.35)]
    if spec.power > 0:
        stats.append(("power", 0.55))
    if spec.cooldown > 0:
        stats.append(("cooldown", 0.35))
    if spec.range > 0 and strategy in {"ranged_focus", "tank_aoe_focus", "special_focus"}:
        stats.append(("range", 0.35))
    if spec.area > 0 and strategy in {"ranged_focus", "tank_aoe_focus", "special_focus"}:
        stats.append(("area", 0.35))
    if mode == "nerf":
        return stats[:4]
    return stats[:5]


def factor_for(stat: str, mode: str, amount: float) -> float:
    if stat in LOWER_IS_BETTER:
        return 1.0 + amount if mode == "nerf" else 1.0 / (1.0 + amount)
    return 1.0 / (1.0 + amount) if mode == "nerf" else 1.0 + amount


def evaluate_candidate(
    candidate: dict[str, Any],
    base_adjustments: list[dict[str, Any]],
    problem_matchups: list[dict[str, Any]],
    policy_dir: str,
    strategies: list[str],
    matches: int,
    seed: int,
    out_dir: Path,
) -> dict[str, Any]:
    candidate_dir = out_dir / candidate["id"]
    candidate_dir.mkdir(parents=True, exist_ok=True)
    reset_balance()
    apply_adjustments(base_adjustments + candidate["adjustments"])
    policies = load_strategy_policies(policy_dir, strategies)
    rows = []
    all_matches = []
    all_rounds = []
    for index, matchup in enumerate(problem_matchups):
        r_strategy = matchup["raspberry_strategy"]
        b_strategy = matchup["blueberry_strategy"]
        matchup_dir = candidate_dir / f"{r_strategy}_vs_{b_strategy}"
        matchup_dir.mkdir(parents=True, exist_ok=True)
        matchup_policy = combined_strategy_policy(policies, r_strategy, b_strategy)
        matchup_agent = strategy_policy_agent_map(r_strategy, b_strategy)
        match_rows, round_rows, aggregate = run_matches(
            matches,
            seed + index * 1009,
            matchup_agent,
            matchup_policy,
            progress_label=f"{candidate['id']} {r_strategy} vs {b_strategy}",
            progress_updates=2,
        )
        write_matches(matchup_dir / "matches.csv", match_rows)
        write_rounds(matchup_dir / "rounds.csv", round_rows)
        write_unit_stats(matchup_dir / "unit_stats.csv", aggregate, matches)
        summary = build_summary(match_rows, round_rows, aggregate, matches, f"matrix_guided:{r_strategy}_vs_{b_strategy}")
        (matchup_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        row = {
            "raspberry_strategy": r_strategy,
            "blueberry_strategy": b_strategy,
            "raspberry_win_rate": summary["match_win_rate"]["raspberry"],
            "blueberry_win_rate": summary["match_win_rate"]["blueberry"],
            "avg_final_control": summary["avg_final_control"],
            "avg_round_duration": summary["avg_round_duration"],
            "raspberry_detected_dominant": dominant_detected_strategy(summary, "raspberry"),
            "blueberry_detected_dominant": dominant_detected_strategy(summary, "blueberry"),
            "strategy_diversity_penalty": summary["strategy_diversity"]["score"],
        }
        rows.append(row)
        all_matches.extend(match_rows)
        all_rounds.extend(round_rows)
        write_matrix(candidate_dir / "mini_matrix.csv", rows)
    score = matrix_guided_score(rows, strategies)
    write_matrix(candidate_dir / "mini_matrix.csv", rows)
    write_matrix_report(
        candidate_dir / "mini_matrix_summary.json",
        matches,
        strategies,
        "",
        rows,
        "strategy_policy",
        0,
        policy_dir,
    )
    result = {
        "candidate_id": candidate["id"],
        "description": candidate["description"],
        "score": score,
        "rows": rows,
        "adjustments": candidate["adjustments"],
    }
    (candidate_dir / "candidate_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def matrix_guided_score(rows: list[dict[str, Any]], strategies: list[str]) -> dict[str, float]:
    if not rows:
        return {
            "score": 999.0,
            "avg_raspberry_win_rate": 0.0,
            "strategy_spread": 1.0,
            "mirror_gap": 1.0,
            "extreme_rate": 1.0,
            "dead_strategy_penalty": 1.0,
            "avg_control_gap": 1.0,
        }
    rates = [row["raspberry_win_rate"] for row in rows]
    avg_r = average(rates)
    strategy_data = strategy_rates(rows, strategies)
    present_strategies = [
        strategy
        for strategy in strategies
        if any(row["raspberry_strategy"] == strategy or row["blueberry_strategy"] == strategy for row in rows)
    ]
    present_rates = [strategy_data[strategy]["combined"] for strategy in present_strategies]
    strategy_spread = (max(present_rates) - min(present_rates)) if present_rates else 1.0
    mirror_rates = [
        abs(row["raspberry_win_rate"] - 0.5)
        for row in rows
        if row["raspberry_strategy"] == row["blueberry_strategy"]
    ]
    mirror_gap = average(mirror_rates) if mirror_rates else 0.0
    extreme_rate = sum(1 for value in rates if value <= 0.05 or value >= 0.95) / len(rates)
    dead_strategy_penalty = sum(
        1
        for strategy in present_strategies
        if strategy_data[strategy]["combined"] <= 0.18 or strategy_data[strategy]["combined"] >= 0.82
    ) / max(1, len(present_strategies))
    avg_control_gap = average([min(1.0, abs(row.get("avg_final_control", 0.0)) / 3.0) for row in rows])
    score = (
        abs(avg_r - 0.5) * 0.22
        + strategy_spread * 0.24
        + mirror_gap * 0.20
        + extreme_rate * 0.18
        + dead_strategy_penalty * 0.10
        + avg_control_gap * 0.06
    )
    return {
        "score": round(score, 6),
        "avg_raspberry_win_rate": round(avg_r, 4),
        "strategy_spread": round(strategy_spread, 4),
        "mirror_gap": round(mirror_gap, 4),
        "extreme_rate": round(extreme_rate, 4),
        "dead_strategy_penalty": round(dead_strategy_penalty, 4),
        "avg_control_gap": round(avg_control_gap, 4),
    }


def write_candidate_evaluations(path: Path, evaluations: list[dict[str, Any]]) -> None:
    rows = []
    for rank, evaluation in enumerate(evaluations, start=1):
        score = evaluation["score"]
        rows.append(
            {
                "rank": rank,
                "candidate_id": evaluation["candidate_id"],
                "score": score["score"],
                "avg_raspberry_win_rate": score["avg_raspberry_win_rate"],
                "strategy_spread": score["strategy_spread"],
                "mirror_gap": score["mirror_gap"],
                "extreme_rate": score["extreme_rate"],
                "dead_strategy_penalty": score["dead_strategy_penalty"],
                "avg_control_gap": score["avg_control_gap"],
                "description": evaluation["description"],
            }
        )
    write_rows(
        path,
        [
            "rank",
            "candidate_id",
            "score",
            "avg_raspberry_win_rate",
            "strategy_spread",
            "mirror_gap",
            "extreme_rate",
            "dead_strategy_penalty",
            "avg_control_gap",
            "description",
        ],
        rows,
    )


def write_master_history(path: Path, selected: dict[str, Any], baseline_score: dict[str, float]) -> None:
    row = {
        "iteration": 1,
        "raspberry_win_rate": selected["score"]["avg_raspberry_win_rate"],
        "blueberry_win_rate": round(1.0 - selected["score"]["avg_raspberry_win_rate"], 4),
        "avg_final_control": "",
        "avg_round_duration": "",
        "balance_score": selected["score"]["score"],
        "strategy_diversity_penalty": "",
        "effective_strategies": "",
        "dominant_strategy_share": "",
        "confirmation_raspberry_win_rate": "",
        "confirmation_blueberry_win_rate": "",
        "confirmation_avg_final_control": "",
        "confirmation_balance_score": "",
        "confirmation_strategy_diversity_penalty": "",
        "confirmation_passed": "",
        "patch_added": selected["description"],
        "stopped": True,
        "baseline_matrix_score": baseline_score.get("score", ""),
    }
    write_rows(path, list(row.keys()), [row])


def write_live_candidate_history(path: Path, evaluations: list[dict[str, Any]], baseline_score: dict[str, float]) -> None:
    rows = []
    for evaluation in sorted(evaluations, key=lambda item: item["candidate_id"]):
        score = evaluation["score"]
        rows.append(
            {
                "iteration": evaluation["candidate_id"].replace("candidate_", "C"),
                "raspberry_win_rate": score["avg_raspberry_win_rate"],
                "blueberry_win_rate": round(1.0 - score["avg_raspberry_win_rate"], 4),
                "avg_final_control": score["avg_control_gap"],
                "avg_round_duration": "",
                "balance_score": score["score"],
                "strategy_diversity_penalty": score["strategy_spread"],
                "effective_strategies": "",
                "dominant_strategy_share": score["extreme_rate"],
                "confirmation_raspberry_win_rate": "",
                "confirmation_blueberry_win_rate": "",
                "confirmation_avg_final_control": "",
                "confirmation_balance_score": "",
                "confirmation_strategy_diversity_penalty": "",
                "confirmation_passed": "",
                "patch_added": evaluation["description"],
                "stopped": False,
                "baseline_matrix_score": baseline_score.get("score", ""),
            }
        )
    write_rows(
        path,
        [
            "iteration",
            "raspberry_win_rate",
            "blueberry_win_rate",
            "avg_final_control",
            "avg_round_duration",
            "balance_score",
            "strategy_diversity_penalty",
            "effective_strategies",
            "dominant_strategy_share",
            "confirmation_raspberry_win_rate",
            "confirmation_blueberry_win_rate",
            "confirmation_avg_final_control",
            "confirmation_balance_score",
            "confirmation_strategy_diversity_penalty",
            "confirmation_passed",
            "patch_added",
            "stopped",
            "baseline_matrix_score",
        ],
        rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", required=True)
    parser.add_argument("--balance-result", required=True)
    parser.add_argument("--policy-dir", required=True)
    parser.add_argument("--out", default="raspberry_blue_sim/live_training_current")
    parser.add_argument("--strategies", nargs="*", default=STRATEGIES)
    parser.add_argument("--problem-limit", type=int, default=14)
    parser.add_argument("--candidate-limit", type=int, default=8)
    parser.add_argument("--candidate-matches", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260613)
    parser.add_argument("--patch-strength", type=float, default=0.055)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_adjustments = read_balance_result(args.balance_result)
    reset_balance()
    apply_adjustments(base_adjustments)

    matrix_rows = read_matrix_csv(args.matrix_csv)
    baseline_score = matrix_guided_score(matrix_rows, args.strategies)
    problem_matchups = select_problem_matchups(matrix_rows, args.strategies, args.problem_limit)
    candidates = build_candidate_patches(matrix_rows, args.strategies, args.patch_strength, args.candidate_limit)

    write_matrix(out_dir / "selected_problem_matchups.csv", problem_matchups)
    (out_dir / "baseline_matrix_score.json").write_text(json.dumps(baseline_score, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "candidate_patches.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    log(
        f"[matrix-guided start] problems={len(problem_matchups)}, candidates={len(candidates)}, "
        f"candidate_matches={args.candidate_matches}, baseline_score={baseline_score['score']}"
    )

    evaluations = []
    for index, candidate in enumerate(candidates, start=1):
        candidate["id"] = f"candidate_{index:02d}"
        log(f"[candidate {index}/{len(candidates)}] start: {candidate['description']}")
        evaluation = evaluate_candidate(
            candidate,
            base_adjustments,
            problem_matchups,
            args.policy_dir,
            args.strategies,
            args.candidate_matches,
            args.seed + index * 10000,
            out_dir / "candidate_evaluations",
        )
        evaluations.append(evaluation)
        log(f"[candidate {index}/{len(candidates)}] done: score={evaluation['score']}")
        write_candidate_evaluations(out_dir / "candidate_evaluations.csv", sorted(evaluations, key=lambda item: item["score"]["score"]))
        write_live_candidate_history(out_dir / "master_history.csv", evaluations, baseline_score)

    evaluations.sort(key=lambda item: item["score"]["score"])
    if not evaluations:
        raise RuntimeError("No matrix-guided candidates were evaluated.")
    write_candidate_evaluations(out_dir / "candidate_evaluations.csv", evaluations)
    selected = evaluations[0]
    accepted_adjustments = base_adjustments + selected["adjustments"]

    reset_balance()
    apply_adjustments(accepted_adjustments)
    result = {
        "mode": "matrix_guided_balance",
        "matrix_csv": args.matrix_csv.replace("\\", "/"),
        "balance_result": args.balance_result.replace("\\", "/"),
        "policy_dir": args.policy_dir.replace("\\", "/"),
        "problem_limit": args.problem_limit,
        "candidate_limit": args.candidate_limit,
        "candidate_matches": args.candidate_matches,
        "seed": args.seed,
        "patch_strength": args.patch_strength,
        "baseline_score": baseline_score,
        "selected_candidate": selected,
        "accepted_adjustments": accepted_adjustments,
        "final_units": export_units(),
    }
    (out_dir / "current_adjustments.json").write_text(
        json.dumps({"accepted_adjustments": accepted_adjustments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "final_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_live_candidate_history(out_dir / "master_history.csv", evaluations, baseline_score)
    log(f"[matrix-guided selected] {selected['candidate_id']}: {selected['description']}")
    log(json.dumps(selected["score"], ensure_ascii=False, indent=2))
    log(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
