import argparse
import json
import random
from pathlib import Path

from balance import apply_adjustments, reset_balance
from config import DT, ROUND_SECONDS, TEAMS
from render_replay import render_gif, snapshot, write_replay
from run_strategy_matrix import combined_strategy_policy, load_strategy_policies, strategy_policy_agent_map
from simulator import RoundSim, TeamState


RASPBERRY_STRATEGIES = [
    "tank_focus",
    "tank_aoe_focus",
    "ranged_focus",
    "swarm_focus",
    "healer_support",
    "upgrade_focus",
    "mixed",
]
BLUEBERRY_ONLY_STRATEGIES = ["suicide_aoe_focus"]
ALL_POLICY_STRATEGIES = RASPBERRY_STRATEGIES + BLUEBERRY_ONLY_STRATEGIES

TARGET_UNITS = {
    "tank_focus": {"raspberry": ["baumkuchen"], "blueberry": ["baumkuchen"]},
    "tank_aoe_focus": {"raspberry": ["baumkuchen", "tart"], "blueberry": ["baumkuchen", "tarte_tatin"]},
    "ranged_focus": {"raspberry": ["tart", "scone"], "blueberry": ["tarte_tatin", "scone"]},
    "swarm_focus": {"raspberry": ["pie"], "blueberry": ["pie"]},
    "healer_support": {"raspberry": ["baumkuchen", "macaron"]},
    "suicide_aoe_focus": {"blueberry": ["pannacotta"]},
    "upgrade_focus": {"raspberry": [], "blueberry": []},
    "mixed": {"raspberry": [], "blueberry": []},
}


def load_balance(path: str) -> None:
    reset_balance()
    if not path:
        return
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_adjustments(payload.get("accepted_adjustments", []))


def run_one_strategy_round(
    policy: dict,
    agent_type: dict,
    seed: int,
    sample_interval: float,
    label: str,
) -> dict:
    rng = random.Random(seed)
    states = {team: TeamState(team) for team in TEAMS}
    round_sim = RoundSim(rng, 1, 1, states, agent_type, policy)
    frames = []
    next_sample_at = 0.0
    now = 0.0
    reason = "time"

    while now < ROUND_SECONDS:
        terminal_reason = round_sim.play_step(now, DT)
        if now + 1e-9 >= next_sample_at:
            frames.append(snapshot(round_sim, now))
            next_sample_at += sample_interval
        if terminal_reason:
            reason = terminal_reason
            break
        now += DT

    round_sim.record_remaining_survival()
    winner = round_sim.decide_winner()
    if not frames or frames[-1]["time"] != round(now, 2):
        frames.append(snapshot(round_sim, now))

    replay = {
        "match_id": 1,
        "round_no": 1,
        "agent_type": agent_type,
        "seed": seed,
        "label": label,
        "winner": winner,
        "reason": reason,
        "duration": round(now, 2),
        "final_control": round_sim.control,
        "frames": frames,
    }
    replay["unit_counts"] = count_units(replay)
    replay["max_upgrades"] = {
        team: max((frame["upgrades"][team] for frame in frames), default=0)
        for team in TEAMS
    }
    return replay


def count_units(replay: dict) -> dict:
    counts = {team: {} for team in TEAMS}
    seen = set()
    for frame in replay["frames"]:
        for unit in frame["units"]:
            key = (unit["team"], unit["id"])
            if key in seen:
                continue
            seen.add(key)
            team_counts = counts[unit["team"]]
            team_counts[unit["key"]] = team_counts.get(unit["key"], 0) + 1
    return counts


def strategy_score(replay: dict, focus_team: str, strategy: str) -> float:
    duration = replay["duration"]
    score = min(duration / 120.0, 1.0) * 2.0
    if duration < 35.0:
        score -= 2.0
    if duration > 175.0:
        score += 0.4
    target_units = TARGET_UNITS.get(strategy, {}).get(focus_team, [])
    counts = replay["unit_counts"].get(focus_team, {})
    score += sum(counts.get(unit, 0) for unit in target_units) * 0.75
    if strategy == "upgrade_focus":
        score += replay["max_upgrades"].get(focus_team, 0) * 2.0
    if strategy == "mixed":
        used_roles = sum(1 for count in counts.values() if count > 0)
        score += used_roles * 0.4
    return score


def pick_replay(policy: dict, agent_type: dict, focus_team: str, strategy: str, base_seed: int, candidates: int, sample_interval: float, label: str) -> dict:
    best = None
    for offset in range(candidates):
        replay = run_one_strategy_round(policy, agent_type, base_seed + offset * 97, sample_interval, label)
        score = strategy_score(replay, focus_team, strategy)
        if best is None or score > best[0]:
            best = (score, replay)
    return best[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-dir", default="raspberry_blue_sim/live_strategy_policy_current")
    parser.add_argument("--balance-result", default="raspberry_blue_sim/live_matrix_balance_loop_current/current_adjustments.json")
    parser.add_argument("--out", default="raspberry_blue_sim/replays/strategy_examples_current")
    parser.add_argument("--seed", type=int, default=253)
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--sample-interval", type=float, default=2.0)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()

    load_balance(args.balance_result)
    policies = load_strategy_policies(args.policy_dir, ALL_POLICY_STRATEGIES)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [
        {
            "name": f"raspberry_{strategy}",
            "focus_team": "raspberry",
            "raspberry_strategy": strategy,
            "blueberry_strategy": "mixed",
            "strategy": strategy,
        }
        for strategy in RASPBERRY_STRATEGIES
    ]
    jobs.append(
        {
            "name": "blueberry_suicide_aoe_focus",
            "focus_team": "blueberry",
            "raspberry_strategy": "mixed",
            "blueberry_strategy": "suicide_aoe_focus",
            "strategy": "suicide_aoe_focus",
        }
    )

    manifest = []
    for index, job in enumerate(jobs):
        policy = combined_strategy_policy(policies, job["raspberry_strategy"], job["blueberry_strategy"])
        agent_type = strategy_policy_agent_map(job["raspberry_strategy"], job["blueberry_strategy"])
        label = f"{job['raspberry_strategy']} vs {job['blueberry_strategy']}"
        replay = pick_replay(
            policy,
            agent_type,
            job["focus_team"],
            job["strategy"],
            args.seed + index * 1000,
            args.candidates,
            args.sample_interval,
            label,
        )
        replay_path = out_dir / f"{job['name']}.json"
        gif_path = out_dir / f"{job['name']}.gif"
        write_replay(str(replay_path), replay)
        render_gif(replay, str(gif_path), args.fps)
        manifest.append(
            {
                **job,
                "seed": replay["seed"],
                "winner": replay["winner"],
                "duration": replay["duration"],
                "final_control": replay["final_control"],
                "unit_counts": replay["unit_counts"],
                "max_upgrades": replay["max_upgrades"],
                "replay": replay_path.name,
                "gif": gif_path.name,
            }
        )
        print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote: {out_dir}")


if __name__ == "__main__":
    main()
