import copy
from dataclasses import asdict, replace
from typing import Any, Dict, List

from config import TEAMS


BASE_TEAMS = copy.deepcopy(TEAMS)


def reset_balance() -> None:
    TEAMS.clear()
    TEAMS.update(copy.deepcopy(BASE_TEAMS))


def apply_adjustments(adjustments: List[Dict[str, Any]]) -> None:
    for adjustment in adjustments:
        team = adjustment["team"]
        unit_key = adjustment["unit"]
        stat = adjustment["stat"]
        factor = float(adjustment.get("factor", 1.0))
        delta = float(adjustment.get("delta", 0.0))
        if unit_key == "__upgrade__":
            current = float(TEAMS[team].get(stat, 1.0))
            TEAMS[team][stat] = round(max(0.01, current * factor + delta), 4)
            continue
        units = TEAMS[team]["units"]
        for index, spec in enumerate(units):
            if spec.key != unit_key:
                continue
            current = getattr(spec, stat)
            value = current * factor + delta
            if stat == "cost":
                value = max(1, int(round(value)))
            else:
                value = round(max(0.01, value), 4)
            units[index] = replace(spec, **{stat: value})
            break


def export_units() -> Dict[str, List[Dict[str, Any]]]:
    return {
        team: [asdict(spec) for spec in data["units"]]
        for team, data in TEAMS.items()
    }


def export_team_settings() -> Dict[str, Dict[str, Any]]:
    return {
        team: {
            "upgrade_cost_factor": data.get("upgrade_cost_factor", 1.0),
            "upgrade_rate_factor": data.get("upgrade_rate_factor", 1.0),
        }
        for team, data in TEAMS.items()
    }


def compact_adjustment(adjustment: Dict[str, Any]) -> str:
    factor = adjustment.get("factor", 1.0)
    delta = adjustment.get("delta", 0.0)
    return f"{adjustment['team']}.{adjustment['unit']}.{adjustment['stat']} factor={factor} delta={delta}"
