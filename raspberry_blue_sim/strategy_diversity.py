from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable

from config import TEAMS


DESIRED_STRATEGIES = [
    "tank_focus",
    "tank_aoe_focus",
    "ranged_focus",
    "swarm_focus",
    "special_focus",
    "upgrade_focus",
    "mixed_composition",
]

UPGRADE_FOCUS_MIN_UPGRADES = 2
UPGRADE_FOCUS_SHORT_MATCH_MIN_UPGRADES = 1
UPGRADE_FOCUS_SHORT_MATCH_MIN_SHARE = 0.18

ROLE_TO_STRATEGY = {
    "tank": "tank_focus",
    "aoe_ranged": "ranged_focus",
    "single_ranged": "ranged_focus",
    "attacker": "swarm_focus",
    "special": "special_focus",
}

STRATEGY_TO_ROLES = {
    "tank_focus": {"tank"},
    "tank_aoe_focus": {"tank", "aoe_ranged"},
    "ranged_focus": {"aoe_ranged", "single_ranged"},
    "swarm_focus": {"attacker"},
    "special_focus": {"special"},
}


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _entropy(counts: Iterable[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    value = 0.0
    for count in counts:
        if count <= 0:
            continue
        p = count / total
        value -= p * math.log(p)
    return value


def classify_strategy(team: str, produced: Dict[str, int], attack_upgrades: int, hp_upgrades: int) -> Dict[str, Any]:
    role_counts: Dict[str, int] = Counter()
    for spec in TEAMS[team]["units"]:
        role_counts[spec.role] += produced.get(spec.key, 0)

    total_units = sum(role_counts.values())
    total_upgrades = attack_upgrades + hp_upgrades
    total_actions = total_units + total_upgrades
    role_shares = {role: round(_safe_divide(count, total_units), 4) for role, count in sorted(role_counts.items())}
    strategy_group_counts = {
        "tank_focus": role_counts.get("tank", 0),
        "tank_aoe_focus": role_counts.get("tank", 0) + role_counts.get("aoe_ranged", 0),
        "ranged_focus": role_counts.get("aoe_ranged", 0) + role_counts.get("single_ranged", 0),
        "swarm_focus": role_counts.get("attacker", 0),
        "special_focus": role_counts.get("special", 0),
    }
    upgrade_share = _safe_divide(total_upgrades, total_actions)

    if attack_upgrades > hp_upgrades:
        upgrade_flavor = "attack_upgrade_focus"
    elif hp_upgrades > attack_upgrades:
        upgrade_flavor = "hp_upgrade_focus"
    elif total_upgrades > 0:
        upgrade_flavor = "balanced_upgrade_focus"
    else:
        upgrade_flavor = ""

    is_upgrade_focus = (
        total_upgrades >= UPGRADE_FOCUS_MIN_UPGRADES
        or (
            total_upgrades >= UPGRADE_FOCUS_SHORT_MATCH_MIN_UPGRADES
            and upgrade_share >= UPGRADE_FOCUS_SHORT_MATCH_MIN_SHARE
        )
    )

    if total_actions == 0:
        strategy = "inactive"
    elif is_upgrade_focus:
        strategy = "upgrade_focus"
    elif total_units == 0:
        strategy = "upgrade_focus"
    else:
        tank_share = _safe_divide(role_counts.get("tank", 0), total_units)
        aoe_share = _safe_divide(role_counts.get("aoe_ranged", 0), total_units)
        tank_aoe_share = tank_share + aoe_share
        if tank_share >= 0.22 and aoe_share >= 0.22 and tank_aoe_share >= 0.58:
            strategy = "tank_aoe_focus"
        else:
            single_strategy_counts = {
                key: strategy_group_counts[key]
                for key in ("tank_focus", "ranged_focus", "swarm_focus", "special_focus")
            }
            dominant_strategy, dominant_count = max(single_strategy_counts.items(), key=lambda item: item[1])
            dominant_share = _safe_divide(dominant_count, total_units)
            strategy = dominant_strategy if dominant_share >= 0.52 else "mixed_composition"

    return {
        "strategy": strategy,
        "total_units": total_units,
        "attack_upgrades": attack_upgrades,
        "hp_upgrades": hp_upgrades,
        "upgrade_share": round(upgrade_share, 4),
        "upgrade_flavor": upgrade_flavor,
        "role_shares": role_shares,
        "strategy_group_shares": {
            strategy: round(_safe_divide(count, total_units), 4)
            for strategy, count in sorted(strategy_group_counts.items())
        },
    }


def summarize_strategy_diversity(match_rows: Iterable[Any]) -> Dict[str, Any]:
    by_team: Dict[str, Dict[str, Any]] = {}
    combined_counts: Counter[str] = Counter()
    combined_wins: Counter[str] = Counter()

    rows = list(match_rows)
    for team in TEAMS:
        counts: Counter[str] = Counter()
        wins: Counter[str] = Counter()
        for row in rows:
            profile = getattr(row, "strategy_by_team", {}).get(team, {})
            strategy = profile.get("strategy", "unknown")
            counts[strategy] += 1
            combined_counts[strategy] += 1
            if getattr(row, "winner", None) == team:
                wins[strategy] += 1
                combined_wins[strategy] += 1

        by_team[team] = _summarize_counts(counts, wins, len(rows))

    combined = _summarize_counts(combined_counts, combined_wins, len(rows) * max(1, len(TEAMS)))
    return {
        "combined": combined,
        "by_team": by_team,
        "score": combined["diversity_penalty"],
    }


def _summarize_counts(counts: Counter[str], wins: Counter[str], total: int) -> Dict[str, Any]:
    total = total or sum(counts.values()) or 1
    known_counts = {strategy: counts.get(strategy, 0) for strategy in DESIRED_STRATEGIES}
    other_counts = {strategy: count for strategy, count in counts.items() if strategy not in known_counts}
    all_counts = {**known_counts, **other_counts}
    entropy = _entropy(all_counts.values())
    max_entropy = math.log(len(DESIRED_STRATEGIES))
    normalized_entropy = _safe_divide(entropy, max_entropy)
    dominant_share = max((_safe_divide(count, total) for count in all_counts.values()), default=0.0)
    effective_strategies = math.exp(entropy) if entropy > 0 else 0.0
    present_strategies = sum(1 for count in known_counts.values() if count > 0)
    low_presence = sum(1 for count in known_counts.values() if _safe_divide(count, total) < 0.04)

    win_rates = {
        strategy: round(_safe_divide(wins.get(strategy, 0), count), 4)
        for strategy, count in all_counts.items()
        if count > 0
    }
    viable = sum(
        1
        for strategy, count in known_counts.items()
        if count >= max(2, total * 0.04) and _safe_divide(wins.get(strategy, 0), count) >= 0.35
    )
    target_effective = min(5.0, len(DESIRED_STRATEGIES))
    entropy_penalty = 1.0 - min(1.0, normalized_entropy)
    dominance_penalty = max(0.0, dominant_share - 0.38) / 0.62
    effective_penalty = max(0.0, target_effective - effective_strategies) / target_effective
    viable_penalty = max(0.0, 3 - viable) / 3
    diversity_penalty = (
        entropy_penalty * 0.40
        + dominance_penalty * 0.25
        + effective_penalty * 0.20
        + viable_penalty * 0.15
    )

    return {
        "strategy_counts": dict(sorted(all_counts.items())),
        "strategy_win_rates": dict(sorted(win_rates.items())),
        "entropy": round(entropy, 6),
        "normalized_entropy": round(normalized_entropy, 6),
        "effective_strategies": round(effective_strategies, 4),
        "present_strategies": present_strategies,
        "viable_strategies": viable,
        "dominant_strategy_share": round(dominant_share, 4),
        "low_presence_strategies": low_presence,
        "diversity_penalty": round(diversity_penalty, 6),
    }


def average_strategy_diversity(summaries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    items = [summary.get("strategy_diversity", {}) for summary in summaries if summary.get("strategy_diversity")]
    if not items:
        return {}

    averaged: Dict[str, Any] = {
        "combined": {},
        "by_team": {team: {} for team in TEAMS},
        "score": round(sum(item.get("score", 0.0) for item in items) / len(items), 6),
    }
    numeric_keys = [
        "entropy",
        "normalized_entropy",
        "effective_strategies",
        "present_strategies",
        "viable_strategies",
        "dominant_strategy_share",
        "low_presence_strategies",
        "diversity_penalty",
    ]
    for key in numeric_keys:
        averaged["combined"][key] = round(
            sum(item.get("combined", {}).get(key, 0.0) for item in items) / len(items),
            6,
        )
    averaged["combined"]["strategy_counts"] = _merge_counter_dicts(item.get("combined", {}).get("strategy_counts", {}) for item in items)

    for team in TEAMS:
        for key in numeric_keys:
            averaged["by_team"][team][key] = round(
                sum(item.get("by_team", {}).get(team, {}).get(key, 0.0) for item in items) / len(items),
                6,
            )
        averaged["by_team"][team]["strategy_counts"] = _merge_counter_dicts(
            item.get("by_team", {}).get(team, {}).get("strategy_counts", {}) for item in items
        )
    return averaged


def _merge_counter_dicts(dicts: Iterable[Dict[str, int]]) -> Dict[str, int]:
    counter: defaultdict[str, float] = defaultdict(float)
    for data in dicts:
        for key, value in data.items():
            counter[key] += value
    return dict(sorted((key, round(value, 4)) for key, value in counter.items()))
