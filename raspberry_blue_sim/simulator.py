from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import math
import random
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config import (
    BASE_CREDITS,
    BLOCK_DISTANCE,
    DT,
    INCOME_AMOUNT,
    INCOME_INTERVAL,
    KILL_REWARD,
    MAP_MAX,
    MAP_MIN,
    MATCH_ROUNDS_TO_WIN,
    ROUND_SECONDS,
    SECTOR_WIDTH,
    SPAWN_OFFSET,
    TEAMS,
    UPGRADE_COST,
    UPGRADE_RATE,
    UnitSpec,
    raw_sector_from_position,
    sector_center,
    sector_from_position,
)
from strategy_diversity import classify_strategy

POLICY_BACKPROP_DISCOUNT = 0.995
MATCH_WIN_REWARD_WEIGHT = 0.60
ROUND_WIN_REWARD_WEIGHT = 0.25
ROUND_STATE_REWARD_WEIGHT = 0.15


@dataclass
class Unit:
    id: int
    team: str
    spec: UnitSpec
    x: float
    hp: float
    max_hp: float
    power: float
    cooldown_left: float = 0.0
    alive_time: float = 0.0


@dataclass
class TeamState:
    name: str
    credits: int = BASE_CREDITS
    upgrade_level: int = 0
    attack_upgrade_level: int = 0
    hp_upgrade_level: int = 0
    produced: Dict[str, int] = field(default_factory=dict)
    kills: Dict[str, int] = field(default_factory=dict)
    damage: Dict[str, float] = field(default_factory=dict)
    healing: Dict[str, float] = field(default_factory=dict)
    deaths: Dict[str, int] = field(default_factory=dict)
    damage_taken: Dict[str, float] = field(default_factory=dict)
    attacks_made: Dict[str, int] = field(default_factory=dict)
    attacks_received: Dict[str, int] = field(default_factory=dict)
    survival_time: Dict[str, float] = field(default_factory=dict)
    focus_fire_hits: Dict[str, int] = field(default_factory=dict)
    focus_fire_events: Dict[str, int] = field(default_factory=dict)
    max_focus_attackers: Dict[str, int] = field(default_factory=dict)


@dataclass
class RoundResult:
    match_id: int
    round_no: int
    winner: str
    duration: float
    final_control: int
    raspberry_upgrades: int
    blueberry_upgrades: int
    reason: str


@dataclass
class MatchResult:
    match_id: int
    winner: str
    raspberry_rounds: int
    blueberry_rounds: int
    rounds_played: int
    raspberry_final_upgrades: int
    blueberry_final_upgrades: int
    strategy_by_team: Dict[str, dict] = field(default_factory=dict)


class HeuristicAgent:
    def __init__(self, team: str, rng: random.Random):
        self.team = team
        self.rng = rng
        self.next_decision_at = 0.0
        self.upgrade_first = rng.random() < 0.35

    def maybe_act(self, sim: "RoundSim", now: float) -> None:
        if now + 1e-9 < self.next_decision_at:
            return
        self.next_decision_at = now + self.rng.uniform(0.7, 1.4)
        state = sim.states[self.team]
        control = sim.control if self.team == "raspberry" else -sim.control
        pressure = sim.front_pressure(self.team)

        if self.upgrade_first and state.upgrade_level == 0 and now < 12:
            if state.credits >= UPGRADE_COST:
                sim.buy_upgrade(self.team, self.choose_upgrade_stat(state))
            return

        if now > 10 and state.credits >= UPGRADE_COST and state.upgrade_level == 0:
            sim.buy_upgrade(self.team, self.choose_upgrade_stat(state))
            return

        if state.credits >= UPGRADE_COST:
            base_upgrade_chance = 0.18 + 0.05 * max(0, control) + 0.04 * max(0, pressure)
            if now > 60:
                base_upgrade_chance += 0.15
            if state.upgrade_level >= 3:
                base_upgrade_chance *= 0.55
            if self.rng.random() < min(0.35, base_upgrade_chance):
                sim.buy_upgrade(self.team, self.choose_upgrade_stat(state))
                return

        if now > 8 and state.credits >= 650:
            reserve_chance = 0.45 + 0.08 * max(0, control) + (0.12 if now > 70 else 0.0)
            if state.upgrade_level == 0:
                reserve_chance += 0.25
            if self.rng.random() < min(0.90, reserve_chance):
                return

        affordable = [u for u in TEAMS[self.team]["units"] if u.cost <= state.credits]
        if not affordable:
            return

        unit = self.choose_unit(affordable, control, pressure, now)
        sim.spawn(self.team, unit)

    def choose_upgrade_stat(self, state: TeamState) -> str:
        if state.attack_upgrade_level < state.hp_upgrade_level:
            return "attack"
        if state.hp_upgrade_level < state.attack_upgrade_level:
            return "hp"
        return self.rng.choice(["attack", "hp"])

    def choose_unit(self, affordable: List[UnitSpec], control: int, pressure: float, now: float) -> UnitSpec:
        weights = []
        for spec in affordable:
            weight = 1.0
            if spec.role == "attacker":
                weight += 1.4
            elif spec.role == "tank":
                weight += 1.0 + max(0, -control) * 0.5
            elif spec.role == "aoe_ranged":
                weight += 0.8 + min(2.0, pressure * 0.6)
            elif spec.role == "single_ranged":
                weight += 0.3 + (0.5 if now > 45 else 0.0)
            elif spec.role == "special":
                weight += 0.5 + (0.8 if now > 35 else 0.0)
            if control <= -2 and spec.role in {"tank", "aoe_ranged", "special"}:
                weight += 1.1
            weights.append(weight)
        return self.rng.choices(affordable, weights=weights, k=1)[0]


class StrategyBiasedAgent:
    def __init__(self, team: str, rng: random.Random, strategy: str):
        self.team = team
        self.rng = rng
        self.strategy = strategy
        self.next_decision_at = 0.0

    def maybe_act(self, sim: "RoundSim", now: float) -> None:
        if now + 1e-9 < self.next_decision_at:
            return
        self.next_decision_at = now + self.rng.uniform(0.8, 1.4)
        actions = sim.available_actions(self.team)
        if not actions:
            return
        sim.apply_action(self.team, self.choose_action(sim, now, actions))

    def choose_action(
        self,
        sim: "RoundSim",
        now: float,
        actions: List[tuple[str, Optional[str]]],
    ) -> tuple[str, Optional[str]]:
        forced = self.forced_upgrade_focus_action(sim, actions)
        if forced:
            return forced
        weighted = [(action, self.action_weight(sim, now, action)) for action in actions]
        weights = [max(0.01, weight) for _, weight in weighted]
        return self.rng.choices([action for action, _ in weighted], weights=weights, k=1)[0]

    def forced_upgrade_focus_action(
        self,
        sim: "RoundSim",
        actions: List[tuple[str, Optional[str]]],
    ) -> Optional[tuple[str, Optional[str]]]:
        if self.strategy != "upgrade_focus":
            return None
        state = sim.states[self.team]
        control = sim.control if self.team == "raspberry" else -sim.control
        legal = set(actions)
        if ("upgrade", "attack") in legal or ("upgrade", "hp") in legal:
            if state.attack_upgrade_level <= state.hp_upgrade_level and ("upgrade", "attack") in legal:
                return ("upgrade", "attack")
            if ("upgrade", "hp") in legal:
                return ("upgrade", "hp")
            return ("upgrade", "attack")
        should_save = state.upgrade_level < 2 or (state.upgrade_level < 3 and control >= -1)
        if should_save and state.credits >= BASE_CREDITS and ("wait", None) in legal:
            return ("wait", None)
        return None

    def action_weight(self, sim: "RoundSim", now: float, action: tuple[str, Optional[str]]) -> float:
        kind, key = action
        state = sim.states[self.team]
        control = sim.control if self.team == "raspberry" else -sim.control
        pressure = sim.front_pressure(self.team)
        weight = 1.0

        if kind == "wait":
            return 0.35 if state.credits < UPGRADE_COST else 0.08
        if kind == "upgrade":
            return self.upgrade_weight(state, key or "attack", now, control)
        if kind != "spawn" or not key:
            return weight

        spec = next(spec for spec in TEAMS[self.team]["units"] if spec.key == key)
        role = spec.role
        if self.strategy == "tank_focus":
            weight *= 8.0 if role == "tank" else 0.45
            if control < 0 and role == "tank":
                weight *= 1.35
        elif self.strategy == "ranged_focus":
            weight *= 7.0 if role in {"aoe_ranged", "single_ranged"} else 0.5
            if pressure > 0 and role == "aoe_ranged":
                weight *= 1.45
        elif self.strategy == "swarm_focus":
            weight *= 8.0 if role == "attacker" else 0.4
            if spec.cost <= 120:
                weight *= 1.4
        elif self.strategy == "special_focus":
            weight *= 8.0 if role == "special" else 0.45
            if now < 20 and role == "special":
                weight *= 0.45
        elif self.strategy == "upgrade_focus":
            weight *= 0.45 if state.upgrade_level < 2 else 0.7
            if state.upgrade_level >= 2:
                weight *= 1.45
        elif self.strategy == "mixed":
            if role == "attacker":
                weight *= 1.8
            elif role == "tank":
                weight *= 1.4 + max(0, -control) * 0.4
            elif role == "aoe_ranged":
                weight *= 1.5 + min(1.5, pressure * 0.4)
            elif role == "single_ranged":
                weight *= 1.2 + (0.4 if now > 45 else 0.0)
            elif role == "special":
                weight *= 1.1 + (0.5 if now > 40 else 0.0)
        return weight

    def upgrade_weight(self, state: TeamState, upgrade_stat: str, now: float, control: int) -> float:
        if self.strategy == "upgrade_focus":
            if state.upgrade_level < 3:
                base = 7.5
            else:
                base = 2.0
        elif self.strategy in {"tank_focus", "swarm_focus"}:
            base = 0.7 if state.upgrade_level == 0 and now < 35 else 1.2
        elif self.strategy == "ranged_focus":
            base = 1.6 if upgrade_stat == "attack" else 0.9
        elif self.strategy == "special_focus":
            base = 1.5 if now > 35 else 0.7
        else:
            base = 1.4 + 0.2 * max(0, control)
        if upgrade_stat == "attack" and state.attack_upgrade_level <= state.hp_upgrade_level:
            base *= 1.15
        if upgrade_stat == "hp" and state.hp_upgrade_level <= state.attack_upgrade_level:
            base *= 1.15
        return base


class MCTSAgent:
    def __init__(self, team: str, rng: random.Random, iterations: int = 8, horizon: float = 8.0):
        self.team = team
        self.rng = rng
        self.iterations = iterations
        self.horizon = horizon
        self.next_decision_at = 0.0

    def maybe_act(self, sim: "RoundSim", now: float) -> None:
        if now + 1e-9 < self.next_decision_at:
            return
        self.next_decision_at = now + 3.0
        actions = sim.available_actions(self.team)
        if not actions:
            return
        sim.apply_action(self.team, self.choose_action(sim, now, actions))

    def choose_action(self, sim: "RoundSim", now: float, actions: List[tuple[str, Optional[str]]]) -> tuple[str, Optional[str]]:
        stats = {action: {"visits": 0, "score": 0.0} for action in actions}
        for iteration in range(self.iterations):
            action = self.select_uct_action(stats, iteration)
            score = self.rollout_score(sim, now, action, iteration)
            stats[action]["visits"] += 1
            stats[action]["score"] += score
        return max(actions, key=lambda action: stats[action]["score"] / max(1, stats[action]["visits"]))

    def select_uct_action(self, stats: Dict[tuple[str, Optional[str]], Dict[str, float]], iteration: int) -> tuple[str, Optional[str]]:
        unvisited = [action for action, values in stats.items() if values["visits"] == 0]
        if unvisited:
            return unvisited[iteration % len(unvisited)]
        total = sum(values["visits"] for values in stats.values())
        exploration = 1.35
        return max(
            stats,
            key=lambda action: (stats[action]["score"] / stats[action]["visits"])
            + exploration * math.sqrt(math.log(total + 1) / stats[action]["visits"]),
        )

    def rollout_score(self, sim: "RoundSim", now: float, action: tuple[str, Optional[str]], iteration: int) -> float:
        clone = copy.deepcopy(sim)
        clone.rng = random.Random(self.rng.randrange(1_000_000_000) + iteration)
        clone.agents = {team: HeuristicAgent(team, clone.rng) for team in TEAMS}
        clone.apply_action(self.team, action)
        end = min(ROUND_SECONDS, now + self.horizon)
        t = now
        reason = None
        while t < end and reason is None:
            reason = clone.play_step(t, DT)
            t += DT
        return clone.evaluate_for(self.team)


def action_to_key(action: tuple[str, Optional[str]]) -> str:
    kind, unit_key = action
    return kind if unit_key is None else f"{kind}:{unit_key}"


def key_to_action(key: str) -> tuple[str, Optional[str]]:
    if ":" not in key:
        return (key, None)
    kind, unit_key = key.split(":", 1)
    return (kind, unit_key)


class PolicyMCTSAgent:
    def __init__(self, team: str, rng: random.Random, policy: dict, training: bool):
        self.team = team
        self.rng = rng
        self.policy = policy
        self.training = training
        self.next_decision_at = 0.0

    def maybe_act(self, sim: "RoundSim", now: float) -> None:
        if now + 1e-9 < self.next_decision_at:
            return
        self.next_decision_at = now + 1.2
        actions = sim.available_actions(self.team)
        if not actions:
            return
        state_key = sim.state_key(self.team, now)
        action = self.opening_upgrade_action(sim, now, actions) or self.choose_action(state_key, actions)
        if self.training:
            sim.policy_traces[self.team].append((state_key, action_to_key(action)))
        sim.apply_action(self.team, action)

    def opening_upgrade_action(
        self,
        sim: "RoundSim",
        now: float,
        actions: List[tuple[str, Optional[str]]],
    ) -> Optional[tuple[str, Optional[str]]]:
        if sim.states[self.team].upgrade_level > 0 or now > 12:
            return None
        legal = set(actions)
        attack_upgrade = ("upgrade", "attack")
        hp_upgrade = ("upgrade", "hp")
        if attack_upgrade in legal and hp_upgrade in legal:
            return self.rng.choice([attack_upgrade, hp_upgrade])
        if attack_upgrade in legal:
            return attack_upgrade
        if hp_upgrade in legal:
            return hp_upgrade
        if ("wait", None) in legal:
            return ("wait", None)
        return None

    def choose_action(self, state_key: str, actions: List[tuple[str, Optional[str]]]) -> tuple[str, Optional[str]]:
        if self.training and self.rng.random() < 0.12:
            return self.rng.choice(actions)
        legal = {action_to_key(action): action for action in actions}
        state = self.policy.get(self.team, {}).get(state_key, {})
        if self.training:
            return self.choose_uct(state, legal)
        return self.choose_best_known(state, legal, actions)

    def choose_uct(self, state: dict, legal: Dict[str, tuple[str, Optional[str]]]) -> tuple[str, Optional[str]]:
        unvisited = [key for key in legal if state.get(key, {}).get("visits", 0) == 0]
        if unvisited:
            return legal[self.rng.choice(unvisited)]
        total = sum(state.get(key, {}).get("visits", 0) for key in legal) or 1
        exploration = 1.2
        best_key = max(
            legal,
            key=lambda key: self.action_value(state, key)
            + exploration * math.sqrt(math.log(total + 1) / state[key]["visits"]),
        )
        return legal[best_key]

    def choose_best_known(self, state: dict, legal: Dict[str, tuple[str, Optional[str]]], actions: List[tuple[str, Optional[str]]]) -> tuple[str, Optional[str]]:
        known = [key for key in legal if state.get(key, {}).get("visits", 0) > 0]
        if not known:
            affordable_units = [action for action in actions if action[0] == "spawn"]
            return self.rng.choice(affordable_units or actions)
        return legal[max(known, key=lambda key: self.action_value(state, key))]

    def action_value(self, state: dict, key: str) -> float:
        node = state.get(key, {})
        visits = node.get("visits", 0)
        return node.get("reward", 0.0) / visits if visits else 0.0


class RoundSim:
    def __init__(
        self,
        rng: random.Random,
        match_id: int,
        round_no: int,
        states: Dict[str, TeamState],
        agent_type,
        policy: Optional[dict] = None,
    ):
        self.rng = rng
        self.match_id = match_id
        self.round_no = round_no
        self.states = states
        self.units: List[Unit] = []
        self.next_unit_id = 1
        self.control = 0
        self.next_income_at = INCOME_INTERVAL
        self.now = 0.0
        self.agent_type = agent_type
        self.policy = policy if policy is not None else {}
        self.policy_traces: Dict[str, List[tuple[str, str]]] = {team: [] for team in TEAMS}
        self.current_focus_counts: Dict[int, int] = {}
        self.agents = self.create_agents(agent_type)
        self.final_scores: Dict[str, float] = {team: 0.5 for team in TEAMS}

    def create_agents(self, agent_type):
        if isinstance(agent_type, dict):
            return {team: self.create_agent(team, agent_type.get(team, "heuristic")) for team in TEAMS}
        return {team: self.create_agent(team, agent_type) for team in TEAMS}

    def create_agent(self, team: str, agent_type: str):
        if agent_type.startswith("strategy:"):
            return StrategyBiasedAgent(team, self.rng, agent_type.split(":", 1)[1])
        if agent_type == "mcts":
            return MCTSAgent(team, self.rng)
        if agent_type == "policy_train":
            return PolicyMCTSAgent(team, self.rng, self.policy, training=True)
        if agent_type == "trained_mcts":
            return PolicyMCTSAgent(team, self.rng, self.policy, training=False)
        return HeuristicAgent(team, self.rng)

    def run(self) -> RoundResult:
        self.now = 0.0
        reason = "time"
        while self.now < ROUND_SECONDS:
            terminal_reason = self.play_step(self.now, DT)
            if terminal_reason:
                reason = terminal_reason
                break
            self.now += DT

        self.record_remaining_survival()
        winner = self.decide_winner()
        self.final_scores = {team: self.evaluate_for(team) for team in TEAMS}
        return RoundResult(
            self.match_id,
            self.round_no,
            winner,
            round(self.now, 2),
            self.control,
            self.states["raspberry"].upgrade_level,
            self.states["blueberry"].upgrade_level,
            reason,
        )

    def play_step(self, now: float, dt: float) -> Optional[str]:
        self.now = now
        for agent in self.agents.values():
            agent.maybe_act(self, now)
        if now + 1e-9 >= self.next_income_at:
            for state in self.states.values():
                state.credits += INCOME_AMOUNT
            self.next_income_at += INCOME_INTERVAL

        self.step_units(dt)
        self.update_control()
        return self.full_control_reason()

    def state_key(self, team: str, now: float) -> str:
        perspective = 1 if team == "raspberry" else -1
        own = self.states[team]
        enemy_team = next(name for name in TEAMS if name != team)
        enemy = self.states[enemy_team]
        own_units = sum(1 for unit in self.units if unit.team == team)
        enemy_units = sum(1 for unit in self.units if unit.team != team)
        pressure = max(-3, min(3, enemy_units - own_units))
        credit_bucket = min(3, own.credits // 500)
        enemy_credit_bucket = min(3, enemy.credits // 500)
        time_bucket = min(5, int(now // 30))
        control = self.control * perspective
        upgrade_diff = max(-3, min(3, own.upgrade_level - enemy.upgrade_level))
        attack_upgrade_diff = max(-3, min(3, own.attack_upgrade_level - enemy.attack_upgrade_level))
        hp_upgrade_diff = max(-3, min(3, own.hp_upgrade_level - enemy.hp_upgrade_level))
        return "|".join(
            [
                f"t{time_bucket}",
                f"c{control}",
                f"cr{credit_bucket}",
                f"ecr{enemy_credit_bucket}",
                f"p{pressure}",
                f"u{upgrade_diff}",
                f"a{attack_upgrade_diff}",
                f"h{hp_upgrade_diff}",
            ]
        )

    def available_actions(self, team: str) -> List[tuple[str, Optional[str]]]:
        state = self.states[team]
        actions: List[tuple[str, Optional[str]]] = []
        if state.credits >= UPGRADE_COST:
            actions.append(("upgrade", "attack"))
            actions.append(("upgrade", "hp"))
        for spec in TEAMS[team]["units"]:
            if state.credits >= spec.cost:
                actions.append(("spawn", spec.key))
        saving_for_first_upgrade = state.upgrade_level == 0 and state.credits >= BASE_CREDITS
        if not actions or saving_for_first_upgrade or (650 <= state.credits < UPGRADE_COST):
            actions.append(("wait", None))
        return actions

    def apply_action(self, team: str, action: tuple[str, Optional[str]]) -> bool:
        kind, unit_key = action
        if kind == "wait":
            return True
        if kind == "upgrade":
            return self.buy_upgrade(team, unit_key or "attack")
        if kind == "spawn" and unit_key:
            spec = next(spec for spec in TEAMS[team]["units"] if spec.key == unit_key)
            return self.spawn(team, spec)
        return False

    def buy_upgrade(self, team: str, upgrade_stat: str) -> bool:
        state = self.states[team]
        if state.credits < UPGRADE_COST:
            return False
        if upgrade_stat not in {"attack", "hp"}:
            return False
        state.credits -= UPGRADE_COST
        state.upgrade_level += 1
        if upgrade_stat == "attack":
            state.attack_upgrade_level += 1
        else:
            state.hp_upgrade_level += 1
        for unit in self.units:
            if unit.team != team:
                continue
            hp, power = self.scaled_stats(team, unit.spec)
            if upgrade_stat == "hp":
                missing_ratio = unit.hp / unit.max_hp if unit.max_hp else 1.0
                unit.max_hp = hp
                unit.hp = min(unit.max_hp, unit.max_hp * missing_ratio)
            else:
                unit.power = power
        return True

    def spawn(self, team: str, spec: UnitSpec) -> bool:
        state = self.states[team]
        if state.credits < spec.cost:
            return False
        state.credits -= spec.cost
        hp, power = self.scaled_stats(team, spec)
        x = self.spawn_position(team)
        unit = Unit(self.next_unit_id, team, spec, x, hp, hp, power)
        self.next_unit_id += 1
        self.units.append(unit)
        state.produced[spec.key] = state.produced.get(spec.key, 0) + 1
        return True

    def scaled_stats(self, team: str, spec: UnitSpec) -> tuple[float, float]:
        state = self.states[team]
        hp = spec.hp
        power = spec.power
        hp = spec.hp * (1 + UPGRADE_RATE * state.hp_upgrade_level)
        if spec.behavior != "heal":
            power = spec.power * (1 + UPGRADE_RATE * state.attack_upgrade_level)
        if spec.behavior == "heal":
            power = spec.power * (1 + UPGRADE_RATE * state.attack_upgrade_level)
        return hp, power

    def spawn_position(self, team: str) -> float:
        if team == "raspberry":
            sector = max(-3, min(0, self.control))
            return sector_center(sector) - SPAWN_OFFSET
        sector = min(3, max(0, self.control))
        return sector_center(sector) + SPAWN_OFFSET

    def step_units(self, dt: float) -> None:
        self.current_focus_counts = self.build_focus_counts()
        for unit in list(self.units):
            if unit.hp <= 0:
                continue
            unit.alive_time += dt
            unit.cooldown_left = max(0.0, unit.cooldown_left - dt)
            if unit.spec.behavior == "heal":
                self.act_healer(unit)
                self.move(unit, dt, allow_blocking=True)
                continue
            target = self.find_target(unit)
            if target and abs(target.x - unit.x) <= unit.spec.range * SECTOR_WIDTH / 10:
                self.attack(unit, target)
            else:
                self.move(unit, dt, allow_blocking=True)
        self.units = [u for u in self.units if u.hp > 0 and MAP_MIN - SECTOR_WIDTH <= u.x <= MAP_MAX + SECTOR_WIDTH]

    def build_focus_counts(self) -> Dict[int, int]:
        counts: Dict[int, int] = {}
        for unit in self.units:
            if unit.hp <= 0 or unit.spec.behavior == "heal" or unit.cooldown_left > 0:
                continue
            target = self.find_target(unit)
            if target and abs(target.x - unit.x) <= unit.spec.range * SECTOR_WIDTH / 10:
                counts[target.id] = counts.get(target.id, 0) + 1
        return counts

    def move(self, unit: Unit, dt: float, allow_blocking: bool) -> None:
        direction = 1 if unit.team == "raspberry" else -1
        if allow_blocking and self.blocked_by_enemy(unit, direction):
            return
        unit.x += direction * unit.spec.speed * dt

    def blocked_by_enemy(self, unit: Unit, direction: int) -> bool:
        for enemy in self.enemies_of(unit.team):
            delta = enemy.x - unit.x
            if direction * delta > 0 and abs(delta) <= BLOCK_DISTANCE:
                return True
        return False

    def find_target(self, unit: Unit) -> Optional[Unit]:
        enemies = list(self.enemies_of(unit.team))
        if not enemies:
            return None
        direction = 1 if unit.team == "raspberry" else -1
        ahead = [e for e in enemies if direction * (e.x - unit.x) >= -1.0]
        pool = ahead or enemies
        return min(pool, key=lambda enemy: abs(enemy.x - unit.x))

    def act_healer(self, unit: Unit) -> None:
        if unit.cooldown_left > 0:
            return
        heal_range = unit.spec.range * SECTOR_WIDTH / 10
        candidates = [
            ally
            for ally in self.units
            if ally.team == unit.team and ally.id != unit.id and ally.hp < ally.max_hp and abs(ally.x - unit.x) <= heal_range
        ]
        if not candidates:
            return
        target = min(candidates, key=lambda ally: ally.hp / ally.max_hp)
        before = target.hp
        target.hp = min(target.max_hp, target.hp + unit.power)
        self.states[unit.team].healing[unit.spec.key] = self.states[unit.team].healing.get(unit.spec.key, 0.0) + target.hp - before
        unit.cooldown_left = unit.spec.cooldown

    def attack(self, unit: Unit, target: Unit) -> None:
        if unit.cooldown_left > 0:
            return
        focus_count = self.current_focus_counts.get(target.id, 1)
        self.record_attack(unit, target, focus_count)
        if unit.spec.behavior == "suicide_aoe":
            radius = unit.spec.area * SECTOR_WIDTH / 10
            victims = [enemy for enemy in self.enemies_of(unit.team) if abs(enemy.x - target.x) <= radius]
            for victim in victims:
                self.apply_damage(unit, victim, unit.power)
            unit.hp = 0
            self.record_death(unit)
            unit.cooldown_left = unit.spec.cooldown
            return
        if unit.spec.area > 0:
            radius = unit.spec.area * SECTOR_WIDTH / 10
            victims = [enemy for enemy in self.enemies_of(unit.team) if abs(enemy.x - target.x) <= radius]
            for victim in victims:
                self.apply_damage(unit, victim, unit.power)
        else:
            self.apply_damage(unit, target, unit.power)
        unit.cooldown_left = unit.spec.cooldown

    def apply_damage(self, attacker: Unit, target: Unit, amount: float) -> None:
        if target.hp <= 0:
            return
        actual = min(amount, target.hp)
        target.hp -= amount
        self.states[attacker.team].damage[attacker.spec.key] = self.states[attacker.team].damage.get(attacker.spec.key, 0.0) + actual
        self.states[target.team].damage_taken[target.spec.key] = self.states[target.team].damage_taken.get(target.spec.key, 0.0) + actual
        if target.hp <= 0:
            self.states[attacker.team].credits += KILL_REWARD
            self.states[attacker.team].kills[attacker.spec.key] = self.states[attacker.team].kills.get(attacker.spec.key, 0) + 1
            self.record_death(target)

    def record_attack(self, attacker: Unit, target: Unit, focus_count: int) -> None:
        attack_state = self.states[attacker.team]
        target_state = self.states[target.team]
        attack_state.attacks_made[attacker.spec.key] = attack_state.attacks_made.get(attacker.spec.key, 0) + 1
        target_state.attacks_received[target.spec.key] = target_state.attacks_received.get(target.spec.key, 0) + 1
        if focus_count >= 2:
            attack_state.focus_fire_hits[attacker.spec.key] = attack_state.focus_fire_hits.get(attacker.spec.key, 0) + 1
            target_state.focus_fire_events[target.spec.key] = target_state.focus_fire_events.get(target.spec.key, 0) + 1
            prev = target_state.max_focus_attackers.get(target.spec.key, 0)
            target_state.max_focus_attackers[target.spec.key] = max(prev, focus_count)

    def record_death(self, unit: Unit) -> None:
        state = self.states[unit.team]
        state.deaths[unit.spec.key] = state.deaths.get(unit.spec.key, 0) + 1
        state.survival_time[unit.spec.key] = state.survival_time.get(unit.spec.key, 0.0) + unit.alive_time

    def record_remaining_survival(self) -> None:
        for unit in self.units:
            if unit.hp <= 0:
                continue
            state = self.states[unit.team]
            state.survival_time[unit.spec.key] = state.survival_time.get(unit.spec.key, 0.0) + unit.alive_time

    def enemies_of(self, team: str) -> Iterable[Unit]:
        return (unit for unit in self.units if unit.team != team and unit.hp > 0)

    def front_pressure(self, team: str) -> float:
        own = sum(1 for unit in self.units if unit.team == team)
        enemy = sum(1 for unit in self.units if unit.team != team)
        return max(0.0, enemy - own) / 5.0

    def update_control(self) -> None:
        raspberry_front = max((u.x for u in self.units if u.team == "raspberry" and u.hp > 0), default=MAP_MIN)
        blueberry_front = min((u.x for u in self.units if u.team == "blueberry" and u.hp > 0), default=MAP_MAX)
        r_sector = sector_from_position(raspberry_front)
        b_sector = sector_from_position(blueberry_front)
        if r_sector > self.control:
            self.control = r_sector
        if b_sector < self.control:
            self.control = b_sector

    def full_control_reason(self) -> Optional[str]:
        raspberry_front = max((u.x for u in self.units if u.team == "raspberry" and u.hp > 0), default=None)
        if raspberry_front is not None and raw_sector_from_position(raspberry_front) > 3:
            return "raspberry_full_control"
        blueberry_front = min((u.x for u in self.units if u.team == "blueberry" and u.hp > 0), default=None)
        if blueberry_front is not None and raw_sector_from_position(blueberry_front) < -3:
            return "blueberry_full_control"
        return None

    def decide_winner(self) -> str:
        if self.control > 0:
            return "raspberry"
        if self.control < 0:
            return "blueberry"
        raspberry_strength = sum(u.hp for u in self.units if u.team == "raspberry")
        blueberry_strength = sum(u.hp for u in self.units if u.team == "blueberry")
        if raspberry_strength == blueberry_strength:
            return self.rng.choice(["raspberry", "blueberry"])
        return "raspberry" if raspberry_strength > blueberry_strength else "blueberry"

    def evaluate_for(self, team: str) -> float:
        perspective = 1 if team == "raspberry" else -1
        winner = self.decide_winner()
        win_score = 1.0 if winner == team else 0.0
        control_score = 0.5 + 0.5 * (self.control * perspective / 3.0)
        own_hp = sum(unit.hp for unit in self.units if unit.team == team)
        enemy_hp = sum(unit.hp for unit in self.units if unit.team != team)
        hp_score = own_hp / (own_hp + enemy_hp) if own_hp + enemy_hp > 0 else 0.5
        own_upgrades = self.states[team].upgrade_level
        enemy_upgrades = sum(state.upgrade_level for name, state in self.states.items() if name != team)
        upgrade_score = max(0.0, min(1.0, 0.5 + 0.15 * (own_upgrades - enemy_upgrades)))
        return 0.50 * win_score + 0.28 * control_score + 0.14 * hp_score + 0.08 * upgrade_score


class MatchSim:
    def __init__(self, rng: random.Random, match_id: int, agent_type, policy: Optional[dict] = None):
        self.rng = rng
        self.match_id = match_id
        self.agent_type = agent_type
        self.policy = policy if policy is not None else {}
        self.states = {team: TeamState(team) for team in TEAMS}
        self.round_results: List[RoundResult] = []
        self.policy_traces: Dict[str, List[tuple[str, str]]] = {team: [] for team in TEAMS}
        self.round_scores: Dict[str, List[float]] = {team: [] for team in TEAMS}

    def run(self) -> MatchResult:
        wins = {"raspberry": 0, "blueberry": 0}
        round_no = 1
        while max(wins.values()) < MATCH_ROUNDS_TO_WIN and round_no <= 3:
            for state in self.states.values():
                state.credits = BASE_CREDITS
            round_sim = RoundSim(self.rng, self.match_id, round_no, self.states, self.agent_type, self.policy)
            result = round_sim.run()
            self.round_results.append(result)
            for team in TEAMS:
                self.policy_traces[team].extend(round_sim.policy_traces[team])
                self.round_scores[team].append(round_sim.final_scores[team])
            wins[result.winner] += 1
            round_no += 1
        winner = "raspberry" if wins["raspberry"] > wins["blueberry"] else "blueberry"
        self.backpropagate_policy(winner, wins)
        strategy_by_team = {
            team: classify_strategy(
                team,
                self.states[team].produced,
                self.states[team].attack_upgrade_level,
                self.states[team].hp_upgrade_level,
            )
            for team in TEAMS
        }
        return MatchResult(
            self.match_id,
            winner,
            wins["raspberry"],
            wins["blueberry"],
            len(self.round_results),
            self.states["raspberry"].upgrade_level,
            self.states["blueberry"].upgrade_level,
            strategy_by_team,
        )

    def backpropagate_policy(self, winner: str, wins: Dict[str, int]) -> None:
        if self.agent_type != "policy_train":
            return
        rounds_played = len(self.round_results) or 1
        for team, trace in self.policy_traces.items():
            if not trace:
                continue
            round_state_score = sum(self.round_scores[team]) / len(self.round_scores[team]) if self.round_scores[team] else 0.5
            final_reward = (
                MATCH_WIN_REWARD_WEIGHT * (1.0 if winner == team else 0.0)
                + ROUND_WIN_REWARD_WEIGHT * (wins[team] / rounds_played)
                + ROUND_STATE_REWARD_WEIGHT * round_state_score
            )
            team_policy = self.policy.setdefault(team, {})
            for distance_from_terminal, (state_key, action_key) in enumerate(reversed(trace)):
                discounted_reward = final_reward * (POLICY_BACKPROP_DISCOUNT ** distance_from_terminal)
                state = team_policy.setdefault(state_key, {})
                node = state.setdefault(action_key, {"visits": 0, "reward": 0.0, "wins": 0})
                node["visits"] += 1
                node["reward"] += discounted_reward
                if winner == team:
                    node["wins"] += 1


def load_policy(path: Optional[str]) -> dict:
    if not path:
        return {}
    policy_path = Path(path)
    if not policy_path.exists():
        return {}
    return json.loads(policy_path.read_text(encoding="utf-8"))


def save_policy(path: str, policy: dict) -> None:
    policy_path = Path(path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")


def run_matches(
    matches: int,
    seed: int,
    agent_type="heuristic",
    policy: Optional[dict] = None,
    progress_label: str = "",
    progress_updates: int = 5,
) -> tuple[List[MatchResult], List[RoundResult], Dict[str, TeamState]]:
    rng = random.Random(seed)
    match_results: List[MatchResult] = []
    round_results: List[RoundResult] = []
    aggregate = {team: TeamState(team, credits=0) for team in TEAMS}
    progress_interval = max(1, matches // max(1, progress_updates)) if progress_label else 0
    for match_id in range(1, matches + 1):
        match = MatchSim(rng, match_id, agent_type, policy)
        match_results.append(match.run())
        round_results.extend(match.round_results)
        for team, state in match.states.items():
            for attr in ("produced", "kills", "deaths", "attacks_made", "attacks_received", "focus_fire_hits", "focus_fire_events"):
                target = getattr(aggregate[team], attr)
                for key, value in getattr(state, attr).items():
                    target[key] = target.get(key, 0) + value
            for attr in ("damage", "healing", "damage_taken", "survival_time"):
                target = getattr(aggregate[team], attr)
                for key, value in getattr(state, attr).items():
                    target[key] = target.get(key, 0.0) + value
            for key, value in state.max_focus_attackers.items():
                aggregate[team].max_focus_attackers[key] = max(aggregate[team].max_focus_attackers.get(key, 0), value)
            aggregate[team].upgrade_level += state.upgrade_level
            aggregate[team].attack_upgrade_level += state.attack_upgrade_level
            aggregate[team].hp_upgrade_level += state.hp_upgrade_level
        if progress_label and (match_id == 1 or match_id == matches or match_id % progress_interval == 0):
            percent = match_id / matches * 100
            wins = {team: sum(1 for row in match_results if row.winner == team) for team in TEAMS}
            print(
                f"[{progress_label}] {match_id}/{matches} matches ({percent:.1f}%) "
                f"wins={wins}",
                flush=True,
            )
    return match_results, round_results, aggregate
