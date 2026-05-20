import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from balance import apply_adjustments, compact_adjustment, export_units, reset_balance
from config import TEAMS
from run_experiment import build_summary, write_matches, write_rounds, write_unit_stats
from simulator import MatchResult, RoundResult, TeamState, run_matches, save_policy
from train_mcts import policy_summary


def log(message: str) -> None:
    print(message, flush=True)


def read_seed_adjustments(path: str) -> List[Dict[str, Any]]:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("accepted_adjustments", [])


def write_balance_result(path: Path, adjustments: List[Dict[str, Any]], summary: dict | None = None) -> None:
    reset_balance()
    apply_adjustments(adjustments)
    payload = {
        "accepted_adjustments": adjustments,
        "final_summary": summary or {},
        "final_units": export_units(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def train_policy(playouts: int, seed: int, policy_path: Path, report_path: Path, label: str = "") -> dict:
    policy: dict = {}
    log(f"[{label}] train start: playouts={playouts}, seed={seed}")
    match_rows, round_rows, aggregate = run_matches(
        playouts,
        seed,
        "policy_train",
        policy,
        progress_label=f"{label} train" if label else "",
    )
    save_policy(str(policy_path), policy)
    wins = {team: sum(1 for row in match_rows if row.winner == team) for team in TEAMS}
    report = {
        "playouts": playouts,
        "seed": seed,
        "match_wins_during_training": wins,
        "match_win_rate_during_training": {team: round(wins[team] / playouts, 4) for team in TEAMS},
        "rounds_played": len(round_rows),
        "avg_final_upgrades_per_match": {
            team: round(aggregate[team].upgrade_level / playouts, 4) for team in TEAMS
        },
        "policy": policy_summary(policy),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[{label}] train done: win_rate={report['match_win_rate_during_training']}, rounds={len(round_rows)}")
    return policy


def train_policy_in_memory(playouts: int, seed: int) -> dict:
    policy: dict = {}
    run_matches(playouts, seed, "policy_train", policy)
    return policy


def merge_aggregate(target: Dict[str, TeamState], source: Dict[str, TeamState]) -> None:
    for team, state in source.items():
        for attr in (
            "produced",
            "kills",
            "deaths",
            "attacks_made",
            "attacks_received",
            "focus_fire_hits",
            "focus_fire_events",
        ):
            target_map = getattr(target[team], attr)
            for key, value in getattr(state, attr).items():
                target_map[key] = target_map.get(key, 0) + value
        for attr in ("damage", "healing", "damage_taken", "survival_time"):
            target_map = getattr(target[team], attr)
            for key, value in getattr(state, attr).items():
                target_map[key] = target_map.get(key, 0.0) + value
        for key, value in state.max_focus_attackers.items():
            target[team].max_focus_attackers[key] = max(target[team].max_focus_attackers.get(key, 0), value)
        target[team].upgrade_level += state.upgrade_level


def offset_match_ids(
    match_rows: List[MatchResult],
    round_rows: List[RoundResult],
    offset: int,
) -> tuple[List[MatchResult], List[RoundResult]]:
    for row in match_rows:
        row.match_id += offset
    for row in round_rows:
        row.match_id += offset
    return match_rows, round_rows


def validate_policy(matches: int, seed: int, policy: dict, out_dir: Path) -> tuple[dict, Dict[str, Any]]:
    match_rows, round_rows, aggregate = run_matches(matches, seed, "trained_mcts", policy)
    write_matches(out_dir / "matches.csv", match_rows)
    write_rounds(out_dir / "rounds.csv", round_rows)
    write_unit_stats(out_dir / "unit_stats.csv", aggregate, matches)
    summary = build_summary(match_rows, round_rows, aggregate, matches, "trained_mcts")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, aggregate


def validate_policy_multi_seed(
    matches: int,
    seeds: List[int],
    policy: dict,
    out_dir: Path,
    label: str = "",
) -> tuple[dict, Dict[str, TeamState]]:
    all_matches: List[MatchResult] = []
    all_rounds: List[RoundResult] = []
    aggregate = {team: TeamState(team, credits=0) for team in TEAMS}

    for index, seed in enumerate(seeds):
        seed_label = f"{label} validation seed {index + 1}/{len(seeds)}" if label else ""
        log(f"[{seed_label}] start: matches={matches}, seed={seed}")
        seed_dir = out_dir / f"validation_seed_{index + 1:02d}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        match_rows, round_rows, seed_aggregate = run_matches(
            matches,
            seed,
            "trained_mcts",
            policy,
            progress_label=seed_label,
        )
        write_matches(seed_dir / "matches.csv", match_rows)
        write_rounds(seed_dir / "rounds.csv", round_rows)
        write_unit_stats(seed_dir / "unit_stats.csv", seed_aggregate, matches)
        seed_summary = build_summary(match_rows, round_rows, seed_aggregate, matches, "trained_mcts")
        (seed_dir / "summary.json").write_text(json.dumps(seed_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        log(
            f"[{seed_label}] done: win_rate={seed_summary['match_win_rate']}, "
            f"avg_control={seed_summary['avg_final_control']}"
        )
        offset_rows, offset_rounds = offset_match_ids(match_rows, round_rows, index * matches)
        all_matches.extend(offset_rows)
        all_rounds.extend(offset_rounds)
        merge_aggregate(aggregate, seed_aggregate)
        (seed_dir / "seed.txt").write_text(str(seed), encoding="utf-8")

    total_matches = matches * len(seeds)
    write_matches(out_dir / "matches.csv", all_matches)
    write_rounds(out_dir / "rounds.csv", all_rounds)
    write_unit_stats(out_dir / "unit_stats.csv", aggregate, total_matches)
    summary = build_summary(all_matches, all_rounds, aggregate, total_matches, "trained_mcts")
    summary["validation_seeds"] = seeds
    summary["matches_per_seed"] = matches
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if label:
        log(
            f"[{label}] validation done: total_matches={total_matches}, "
            f"win_rate={summary['match_win_rate']}, avg_control={summary['avg_final_control']}"
        )
    return summary, aggregate


def contribution_score(row: dict) -> float:
    return (
        float(row.get("damage_per_match", 0)) * 1.0
        + float(row.get("kills_per_match", 0)) * 80.0
        + float(row.get("produced_per_match", 0)) * 8.0
        + float(row.get("focus_fire_hits", 0)) * 0.8
    )


def read_unit_rows(path: Path, team: str) -> List[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row["team"] == team]


def get_spec(team: str, unit_key: str):
    return next(spec for spec in TEAMS[team]["units"] if spec.key == unit_key)


def candidate_stat_options(row: dict, team: str, unit_key: str, strength: float, mode: str) -> List[tuple[str, float]]:
    spec = get_spec(team, unit_key)
    options: List[tuple[str, float]] = []
    nerf = mode == "nerf"

    if float(row.get("damage_per_match", 0)) > 0 and spec.power > 0:
        options.append(("power", 1.0 / (1.0 + strength) if nerf else 1.0 + strength * 0.75))
    if float(row.get("team_production_share", 0)) >= 0.18:
        options.append(("cost", 1.0 + strength if nerf else 1.0 / (1.0 + strength * 0.75)))
    if spec.area > 0 and float(row.get("focus_fire_hits", 0)) > 0:
        options.append(("area", 1.0 / (1.0 + strength) if nerf else 1.0 + strength * 0.6))
    if float(row.get("avg_survival_time", 0)) >= 8 and spec.hp > 0:
        options.append(("hp", 1.0 / (1.0 + strength * 0.8) if nerf else 1.0 + strength * 0.6))
    if spec.speed > 0:
        options.append(("speed", 1.0 / (1.0 + strength * 0.7) if nerf else 1.0 + strength * 0.5))
    if not options:
        options.append(("cost", 1.0 + strength if nerf else 1.0 / (1.0 + strength * 0.75)))
    return options


def build_candidate_patches(
    validation_dir: Path,
    dominant_team: str,
    underdog_team: str,
    adjustment_counts: Dict[str, int],
    strength: float,
    max_candidates: int,
) -> List[Dict[str, Any]]:
    dominant_rows = sorted(read_unit_rows(validation_dir / "unit_stats.csv", dominant_team), key=contribution_score, reverse=True)
    underdog_rows = sorted(read_unit_rows(validation_dir / "unit_stats.csv", underdog_team), key=contribution_score, reverse=True)
    if not dominant_rows:
        raise RuntimeError(f"No unit rows found for {dominant_team}")
    if not underdog_rows:
        raise RuntimeError(f"No unit rows found for {underdog_team}")

    candidates: List[Dict[str, Any]] = []
    seen = set()
    pools = [
        (dominant_team, dominant_rows[:3], "nerf"),
        (underdog_team, underdog_rows[:3], "buff"),
    ]
    for team, rows, mode in pools:
        for row in rows:
            unit_key = row["unit_key"]
            prefix = f"{team}.{unit_key}"
            options = sorted(
                candidate_stat_options(row, team, unit_key, strength, mode),
                key=lambda item: adjustment_counts.get(f"{prefix}.{item[0]}", 0),
            )
            for stat, factor in options:
                key = (team, unit_key, stat, round(factor, 4))
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({"team": team, "unit": unit_key, "stat": stat, "factor": round(factor, 4)})
                if len(candidates) >= max_candidates:
                    return candidates
    return candidates


def balance_score(summary: dict, target: float, control_weight: float) -> float:
    raspberry_rate = float(summary["match_win_rate"]["raspberry"])
    win_gap = abs(raspberry_rate - target)
    control_gap = min(1.0, abs(float(summary["avg_final_control"])) / 3.0)
    return round(win_gap + control_weight * control_gap, 6)


def evaluate_candidate_patch(
    adjustments: List[Dict[str, Any]],
    patch: Dict[str, Any],
    policy: dict,
    candidate_playouts: int,
    train_seed: int,
    matches: int,
    seeds: List[int],
    target: float,
    control_weight: float,
    label: str = "",
) -> Dict[str, Any]:
    if label:
        log(f"[{label}] candidate start: {compact_adjustment(patch)}")
    reset_balance()
    apply_adjustments(adjustments + [patch])
    candidate_policy = train_policy_in_memory(candidate_playouts, train_seed) if candidate_playouts > 0 else policy
    summaries = []
    for seed_index, seed in enumerate(seeds):
        seed_label = f"{label} seed {seed_index + 1}/{len(seeds)}" if label else ""
        match_rows, round_rows, aggregate = run_matches(
            matches,
            seed,
            "trained_mcts",
            candidate_policy,
            progress_label=seed_label,
            progress_updates=2,
        )
        summaries.append(build_summary(match_rows, round_rows, aggregate, matches, "trained_mcts"))
    raspberry_rate = sum(item["match_win_rate"]["raspberry"] for item in summaries) / len(summaries)
    blueberry_rate = sum(item["match_win_rate"]["blueberry"] for item in summaries) / len(summaries)
    avg_control = sum(item["avg_final_control"] for item in summaries) / len(summaries)
    avg_duration = sum(item["avg_round_duration"] for item in summaries) / len(summaries)
    summary = {
        "match_win_rate": {
            "raspberry": round(raspberry_rate, 4),
            "blueberry": round(blueberry_rate, 4),
        },
        "avg_final_control": round(avg_control, 4),
        "avg_round_duration": round(avg_duration, 4),
    }
    result = {
        "patch": patch,
        "patch_text": compact_adjustment(patch),
        "score": balance_score(summary, target, control_weight),
        "summary": summary,
    }
    if label:
        log(
            f"[{label}] candidate done: score={result['score']}, "
            f"win_rate={summary['match_win_rate']}, avg_control={summary['avg_final_control']}"
        )
    return result


def write_candidate_evaluations(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "rank",
                "score",
                "raspberry_win_rate",
                "blueberry_win_rate",
                "avg_final_control",
                "avg_round_duration",
                "patch",
            ]
        )
        for index, row in enumerate(rows, start=1):
            summary = row["summary"]
            writer.writerow(
                [
                    index,
                    row["score"],
                    summary["match_win_rate"]["raspberry"],
                    summary["match_win_rate"]["blueberry"],
                    summary["avg_final_control"],
                    summary["avg_round_duration"],
                    row["patch_text"],
                ]
            )


def write_master_history(path: Path, rows: List[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "iteration",
                "raspberry_win_rate",
                "blueberry_win_rate",
                "avg_final_control",
                "avg_round_duration",
                "balance_score",
                "patch_added",
                "stopped",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["iteration"],
                    row["raspberry_win_rate"],
                    row["blueberry_win_rate"],
                    row["avg_final_control"],
                    row["avg_round_duration"],
                    row["balance_score"],
                    row["patch_added"],
                    row["stopped"],
                ]
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-balance", default="raspberry_blue_sim/balance_out/balance_result.json")
    parser.add_argument("--out", default="raspberry_blue_sim/iterative_balance_runs")
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--playouts", type=int, default=500)
    parser.add_argument("--matches", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target", type=float, default=0.5)
    parser.add_argument("--tolerance", type=float, default=0.05)
    parser.add_argument("--patch-strength", type=float, default=0.15)
    parser.add_argument("--validation-seeds", type=int, default=3)
    parser.add_argument("--candidate-matches", type=int, default=20)
    parser.add_argument("--candidate-playouts", type=int, default=100)
    parser.add_argument("--candidate-seeds", type=int, default=3)
    parser.add_argument("--candidate-limit", type=int, default=8)
    parser.add_argument("--control-weight", type=float, default=0.25)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    adjustments = read_seed_adjustments(args.seed_balance)
    adjustment_counts: Dict[str, int] = {}
    history: List[dict] = []
    log(
        "[experiment start] "
        f"out={out_dir}, max_iterations={args.max_iterations}, playouts={args.playouts}, "
        f"matches={args.matches}, validation_seeds={args.validation_seeds}, "
        f"candidate_matches={args.candidate_matches}, candidate_seeds={args.candidate_seeds}"
    )

    for iteration in range(1, args.max_iterations + 1):
        iteration_dir = out_dir / f"iteration_{iteration:02d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        iteration_label = f"iteration {iteration}/{args.max_iterations}"
        log(f"\n[{iteration_label}] start: adjustments={len(adjustments)}")

        reset_balance()
        apply_adjustments(adjustments)
        write_balance_result(iteration_dir / "balance_before_validation.json", adjustments)

        policy_path = iteration_dir / "policy.json"
        train_report_path = iteration_dir / "train_report.json"
        policy = train_policy(args.playouts, args.seed + iteration * 1000, policy_path, train_report_path, iteration_label)
        validation_seeds = [args.seed + iteration * 1000 + 501 + seed_index * 10000 for seed_index in range(args.validation_seeds)]
        summary, _ = validate_policy_multi_seed(args.matches, validation_seeds, policy, iteration_dir, iteration_label)

        raspberry_rate = summary["match_win_rate"]["raspberry"]
        blueberry_rate = summary["match_win_rate"]["blueberry"]
        gap = abs(raspberry_rate - args.target)
        score = balance_score(summary, args.target, args.control_weight)
        stopped = gap <= args.tolerance
        patch_added = ""

        if not stopped:
            dominant_team = "raspberry" if raspberry_rate > blueberry_rate else "blueberry"
            underdog_team = "blueberry" if dominant_team == "raspberry" else "raspberry"
            dominance = abs(raspberry_rate - blueberry_rate)
            strength = args.patch_strength * (1.0 + dominance * 0.75)
            log(
                f"[{iteration_label}] patch search: dominant={dominant_team}, "
                f"underdog={underdog_team}, strength={strength:.4f}"
            )
            candidates = build_candidate_patches(
                iteration_dir,
                dominant_team,
                underdog_team,
                adjustment_counts,
                strength,
                args.candidate_limit,
            )
            candidate_seeds = [args.seed + iteration * 1000 + 20000 + seed_index * 3000 for seed_index in range(args.candidate_seeds)]
            log(f"[{iteration_label}] candidates={len(candidates)}")
            evaluations = []
            for candidate_index, candidate in enumerate(candidates):
                evaluations.append(
                    evaluate_candidate_patch(
                        adjustments,
                        candidate,
                        policy,
                        args.candidate_playouts,
                        args.seed + iteration * 1000 + 50000 + candidate_index * 500,
                        args.candidate_matches,
                        candidate_seeds,
                        args.target,
                        args.control_weight,
                        f"{iteration_label} candidate {candidate_index + 1}/{len(candidates)}",
                    )
                )
            evaluations.sort(key=lambda item: item["score"])
            write_candidate_evaluations(iteration_dir / "candidate_evaluations.csv", evaluations)
            patch = evaluations[0]["patch"]
            adjustments.append(patch)
            count_key = f"{patch['team']}.{patch['unit']}.{patch['stat']}"
            adjustment_counts[count_key] = adjustment_counts.get(count_key, 0) + 1
            patch_added = compact_adjustment(patch)
            log(f"[{iteration_label}] selected patch: {patch_added}")
            write_balance_result(iteration_dir / "balance_after_patch.json", adjustments, summary)
        else:
            write_balance_result(iteration_dir / "balance_final.json", adjustments, summary)
            log(f"[{iteration_label}] target reached: gap={gap:.4f}, tolerance={args.tolerance}")

        row = {
            "iteration": iteration,
            "raspberry_win_rate": raspberry_rate,
            "blueberry_win_rate": blueberry_rate,
            "avg_final_control": summary["avg_final_control"],
            "avg_round_duration": summary["avg_round_duration"],
            "balance_score": score,
            "patch_added": patch_added,
            "stopped": stopped,
        }
        history.append(row)
        write_master_history(out_dir / "master_history.csv", history)
        (out_dir / "current_adjustments.json").write_text(
            json.dumps({"accepted_adjustments": adjustments}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log(f"[{iteration_label}] summary: {json.dumps(row, ensure_ascii=False)}")
        if stopped:
            break

    reset_balance()
    apply_adjustments(adjustments)
    result = {
        "target": args.target,
        "tolerance": args.tolerance,
        "playouts_per_iteration": args.playouts,
        "validation_matches": args.matches,
        "validation_seeds": args.validation_seeds,
        "candidate_matches": args.candidate_matches,
        "candidate_playouts": args.candidate_playouts,
        "candidate_seeds": args.candidate_seeds,
        "control_weight": args.control_weight,
        "iterations_completed": len(history),
        "final_history_row": history[-1] if history else {},
        "accepted_adjustments": adjustments,
        "final_units": export_units(),
    }
    (out_dir / "final_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps(result, ensure_ascii=False, indent=2))
    log(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
