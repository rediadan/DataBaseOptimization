from dataclasses import dataclass
import math


@dataclass(frozen=True)
class UnitSpec:
    key: str
    role: str
    name: str
    cost: int
    hp: float
    speed: float
    power: float
    cooldown: float
    range: float
    area: float
    behavior: str = "attack"


ROUND_SECONDS = 180.0
MATCH_ROUNDS_TO_WIN = 2
DT = 0.5
SECTOR_WIDTH = 22.0
MAP_MIN = -3.5 * SECTOR_WIDTH
MAP_MAX = 3.5 * SECTOR_WIDTH
BASE_CREDITS = 500
INCOME_INTERVAL = 10.0
INCOME_AMOUNT = 500
KILL_REWARD = 50
UPGRADE_COST = 1000
UPGRADE_RATE = 0.30
SPAWN_OFFSET = 4.0
BLOCK_DISTANCE = 0.9


TEAMS = {
    "raspberry": {
        "display": "라즈베리",
        "side": -1,
        "upgrade_stat": "attack",
        "units": [
            UnitSpec("pie", "attacker", "파이", 80, 130, 0.8, 40, 1.0, 1.0, 0.0),
            UnitSpec("tart", "aoe_ranged", "타르트", 280, 250, 0.6, 20, 2.0, 6.0, 1.2),
            UnitSpec("baumkuchen", "tank", "바움쿠헨", 250, 420, 0.8, 10, 1.8, 0.5, 0.0),
            UnitSpec("scone", "single_ranged", "스콘", 500, 300, 0.5, 100, 1.8, 3.0, 0.0),
            UnitSpec("macaron", "special", "마카롱", 300, 50, 1.2, 50, 1.5, 2.5, 1.0, "heal"),
        ],
    },
    "blueberry": {
        "display": "블루베리",
        "side": 1,
        "upgrade_stat": "hp",
        "units": [
            UnitSpec("pie", "attacker", "파이", 100, 100, 1.0, 70, 1.0, 1.0, 0.0),
            UnitSpec("tarte_tatin", "aoe_ranged", "타르트·타탱", 180, 180, 1.0, 50, 3.0, 4.0, 2.5),
            UnitSpec("baumkuchen", "tank", "바움쿠헨", 250, 300, 1.0, 30, 1.0, 0.5, 0.0),
            UnitSpec("scone", "single_ranged", "스콘", 500, 200, 0.8, 150, 2.0, 3.0, 0.0),
            UnitSpec("pannacotta", "special", "판나코타", 400, 50, 1.5, 400, 0.5, 1.0, 6.5, "suicide_aoe"),
        ],
    },
}


def raw_sector_from_position(position: float) -> int:
    ratio = position / SECTOR_WIDTH
    if ratio >= 0:
        return int(math.floor(ratio + 0.5))
    return int(math.ceil(ratio - 0.5))


def sector_from_position(position: float) -> int:
    return max(-3, min(3, raw_sector_from_position(position)))


def sector_center(sector: int) -> float:
    return max(MAP_MIN, min(MAP_MAX, sector * SECTOR_WIDTH))
