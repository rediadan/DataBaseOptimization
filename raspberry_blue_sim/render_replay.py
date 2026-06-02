import argparse
import json
import random
from pathlib import Path

import matplotlib.animation as animation
import matplotlib.pyplot as plt

from balance import apply_adjustments, reset_balance
from config import DT, MAP_MAX, MAP_MIN, ROUND_SECONDS, SECTOR_WIDTH, TEAMS, sector_center
from simulator import RoundSim, TeamState, load_policy


TEAM_COLORS = {
    "raspberry": "#d4485b",
    "blueberry": "#3567d6",
}

UNIT_MARKERS = {
    "pie": "o",
    "tart": "s",
    "tarte_tatin": "s",
    "baumkuchen": "D",
    "scone": "^",
    "macaron": "P",
    "pannacotta": "X",
}


def apply_balance_result(path: str) -> None:
    reset_balance()
    if not path:
        return
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    apply_adjustments(payload.get("accepted_adjustments", []))


def snapshot(round_sim: RoundSim, now: float) -> dict:
    return {
        "time": round(now, 2),
        "control": round_sim.control,
        "credits": {team: round_sim.states[team].credits for team in TEAMS},
        "upgrades": {team: round_sim.states[team].upgrade_level for team in TEAMS},
        "attack_upgrades": {team: round_sim.states[team].attack_upgrade_level for team in TEAMS},
        "hp_upgrades": {team: round_sim.states[team].hp_upgrade_level for team in TEAMS},
        "units": [
            {
                "id": unit.id,
                "team": unit.team,
                "key": unit.spec.key,
                "x": round(unit.x, 3),
                "hp": round(max(0.0, unit.hp), 3),
                "max_hp": round(unit.max_hp, 3),
            }
            for unit in round_sim.units
            if unit.hp > 0
        ],
    }


def run_one_round(policy: dict, agent_type, seed: int, sample_interval: float) -> dict:
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

    return {
        "match_id": 1,
        "round_no": 1,
        "agent_type": agent_type,
        "seed": seed,
        "winner": winner,
        "reason": reason,
        "duration": round(now, 2),
        "final_control": round_sim.control,
        "frames": frames,
    }


def write_replay(path: str, replay: dict) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")


def render_gif(replay: dict, out_path: str, fps: int) -> None:
    frames = replay["frames"]
    fig, ax = plt.subplots(figsize=(12, 3.8))
    fig.patch.set_facecolor("#f7f7f3")
    ax.set_facecolor("#fbfaf6")

    def draw(frame_index: int):
        frame = frames[frame_index]
        ax.clear()
        ax.set_facecolor("#fbfaf6")
        ax.set_xlim(MAP_MIN - 5, MAP_MAX + 5)
        ax.set_ylim(-1.2, 1.2)
        ax.set_yticks([])
        ax.set_xlabel("lane position")
        ax.set_title(
            f"UCT-backprop MCTS replay | t={frame['time']:.1f}s | "
            f"control={frame['control']} | winner={replay['winner']}",
            fontsize=12,
        )

        for sector in range(-3, 4):
            x = sector_center(sector)
            ax.axvline(x, color="#d0d0c8", linewidth=1)
            ax.text(x, -1.03, str(sector), ha="center", va="center", fontsize=9, color="#565656")

        control_x = sector_center(frame["control"])
        ax.axvline(control_x, color="#222222", linewidth=2.5, alpha=0.85)
        ax.text(control_x, 1.0, "control", ha="center", va="center", fontsize=9, color="#222222")

        ax.hlines(0, MAP_MIN, MAP_MAX, color="#9b9b92", linewidth=2)
        ax.text(MAP_MIN, 0.86, "Raspberry", color=TEAM_COLORS["raspberry"], fontsize=11, weight="bold")
        ax.text(MAP_MAX, 0.86, "Blueberry", color=TEAM_COLORS["blueberry"], fontsize=11, weight="bold", ha="right")
        ax.text(
            MAP_MIN,
            0.68,
            f"R credits {frame['credits']['raspberry']} | up {frame['upgrades']['raspberry']}",
            color=TEAM_COLORS["raspberry"],
            fontsize=9,
        )
        ax.text(
            MAP_MAX,
            0.68,
            f"B credits {frame['credits']['blueberry']} | up {frame['upgrades']['blueberry']}",
            color=TEAM_COLORS["blueberry"],
            fontsize=9,
            ha="right",
        )
        ax.text(
            MAP_MIN,
            0.52,
            f"R attack {frame['attack_upgrades']['raspberry']} | hp {frame['hp_upgrades']['raspberry']}",
            color=TEAM_COLORS["raspberry"],
            fontsize=8,
        )
        ax.text(
            MAP_MAX,
            0.52,
            f"B attack {frame['attack_upgrades']['blueberry']} | hp {frame['hp_upgrades']['blueberry']}",
            color=TEAM_COLORS["blueberry"],
            fontsize=8,
            ha="right",
        )

        for unit in frame["units"]:
            y = 0.23 if unit["team"] == "raspberry" else -0.23
            hp_ratio = unit["hp"] / unit["max_hp"] if unit["max_hp"] else 1.0
            size = 55 + 120 * max(0.15, hp_ratio)
            marker = UNIT_MARKERS.get(unit["key"], "o")
            ax.scatter(
                unit["x"],
                y,
                s=size,
                marker=marker,
                color=TEAM_COLORS[unit["team"]],
                edgecolors="#1c1c1c",
                linewidths=0.5,
                alpha=0.86,
            )
            ax.plot(
                [unit["x"] - 1.8, unit["x"] + 1.8],
                [y + 0.15, y + 0.15],
                color="#2e2e2e",
                linewidth=1.0,
                alpha=0.45,
            )
            ax.plot(
                [unit["x"] - 1.8, unit["x"] - 1.8 + 3.6 * hp_ratio],
                [y + 0.15, y + 0.15],
                color="#43a047",
                linewidth=1.8,
            )

        legend_text = "circle pie | square aoe | diamond tank | triangle scone | plus/heavy special"
        ax.text(0.5, 0.04, legend_text, transform=ax.transAxes, ha="center", fontsize=8, color="#555555")
        ax.text(
            0.5,
            0.94,
            f"round duration {replay['duration']}s | reason {replay['reason']} | final control {replay['final_control']}",
            transform=ax.transAxes,
            ha="center",
            fontsize=9,
            color="#555555",
        )

    ani = animation.FuncAnimation(fig, draw, frames=len(frames), interval=1000 / fps)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ani.save(output, writer=animation.PillowWriter(fps=fps))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="")
    parser.add_argument("--balance-result", required=True)
    parser.add_argument("--agent", default="policy_train")
    parser.add_argument("--raspberry-agent", default="")
    parser.add_argument("--blueberry-agent", default="")
    parser.add_argument("--seed", type=int, default=91042)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--replay-out", default="raspberry_blue_sim/replays/best_mcts_round.json")
    parser.add_argument("--gif-out", default="raspberry_blue_sim/replays/best_mcts_round.gif")
    parser.add_argument("--fps", type=int, default=12)
    args = parser.parse_args()

    apply_balance_result(args.balance_result)
    policy = load_policy(args.policy) if args.policy else {}
    agent_type = args.agent
    if args.raspberry_agent or args.blueberry_agent:
        agent_type = {
            "raspberry": args.raspberry_agent or args.agent,
            "blueberry": args.blueberry_agent or args.agent,
        }
    replay = run_one_round(policy, agent_type, args.seed, args.sample_interval)
    write_replay(args.replay_out, replay)
    render_gif(replay, args.gif_out, args.fps)
    print(json.dumps({k: replay[k] for k in ("winner", "reason", "duration", "final_control")}, indent=2))
    print(f"replay wrote: {args.replay_out}")
    print(f"gif wrote: {args.gif_out}")


if __name__ == "__main__":
    main()
