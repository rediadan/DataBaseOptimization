from __future__ import annotations

from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


OUT = Path("raspberry_blue_sim/docs/raspberry_blue_game_spec.xlsx")


def col_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell_xml(row_index: int, col_index: int, value) -> str:
    ref = f"{col_name(col_index)}{row_index}"
    text = "" if value is None else str(value)
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def sheet_xml(rows: list[list[object]]) -> str:
    max_cols = max((len(row) for row in rows), default=1)
    cols = "".join(f'<col min="{i}" max="{i}" width="22" customWidth="1"/>' for i in range(1, max_cols + 1))
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(cell_xml(row_index, col_index, value) for col_index, value in enumerate(row, start=1))
        body.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{cols}</cols>"
        f"<sheetData>{''.join(body)}</sheetData>"
        "</worksheet>"
    )


def workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def workbook_rels_xml(sheet_names: list[str]) -> str:
    rels = [
        '<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{0}.xml"/>'.format(index)
        for index in range(1, len(sheet_names) + 1)
    ]
    rels.append(
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}"
        "</Relationships>"
    )


def content_types_xml(sheet_names: list[str]) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    overrides.extend(
        '<Override PartName="/xl/worksheets/sheet{0}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'.format(index)
        for index in range(1, len(sheet_names) + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}"
        "</Types>"
    )


ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    "</styleSheet>"
)


def rows_overview() -> list[list[object]]:
    return [
        ["라즈베리블루 게임 설명서", "", "", ""],
        ["작성일", str(date(2026, 6, 1)), "기준", "Python 시뮬레이터 현재 규칙"],
        ["한 줄 설명", "라즈베리 팀과 블루베리 팀이 1차선 전장에서 유닛을 생산하고 업그레이드하며 점령선을 밀어 승리하는 비대칭 실시간 전략 물량 게임"],
        ["핵심 목표", "3분 동안 더 많은 구간을 점령하거나, 제한 시간 전에 상대 끝 구간을 완전히 밀어 라운드 승리"],
        ["매치 구조", "3판 2선승제", "라운드 시간", "180초"],
        ["팀", "라즈베리 / 블루베리", "유닛 구조", "각 팀 5종"],
        ["주요 자원", "크레딧", "사용처", "유닛 생산, 공격 업그레이드, 체력 업그레이드"],
        ["현재 중요한 주의점", "2026-06-01에 업그레이드 규칙을 수정함. 이전 밸런스 학습 결과는 업그레이드 수정 전 규칙 기준이라 재학습이 필요함."],
    ]


def rows_rules() -> list[list[object]]:
    return [
        ["항목", "내용"],
        ["장르", "1차선 실시간 전략 물량전 / 자동 전투 / 점령선 밀기"],
        ["플레이어 목표", "유닛을 생산하고 업그레이드를 선택해 전선을 밀어 더 많은 구간을 점령한다."],
        ["라운드 시작", "양 팀 모두 기본 크레딧 500으로 시작한다."],
        ["행동 방식", "버튼을 누르면 조건 만족 시 즉시 생산 또는 즉시 업그레이드가 실행된다."],
        ["아군 충돌", "아군끼리는 겹칠 수 있다. 물량이 한 지점에 쌓일 수 있다."],
        ["적군 충돌", "상대 유닛에게는 막힌다. 막힘 거리 기준은 0.9 맵 단위다."],
        ["공격 방식", "사거리 안에 들어온 적을 자동 공격한다. 단일 공격, 범위 공격, 힐, 자폭 범위 공격이 존재한다."],
        ["업그레이드 유지", "라운드가 끝나도 업그레이드 레벨은 매치 안에서 유지된다. 크레딧은 라운드마다 500으로 리셋된다."],
        ["비대칭성", "양 팀은 같은 역할군 5종을 가지지만 비용/체력/속도/공격력/특수 유닛이 다르다."],
    ]


def rows_map() -> list[list[object]]:
    rows = [
        ["항목", "값", "설명"],
        ["구간", "-3, -2, -1, 0, 1, 2, 3", "총 7구간"],
        ["구간 길이", 22.0, "중앙 구간을 이동하는 데 약 22초가 걸렸다는 Unity 기준을 반영"],
        ["맵 최소 좌표", -77.0, "-3.5 * 22"],
        ["맵 최대 좌표", 77.0, "3.5 * 22"],
        ["구간 중심", "sector * 22", "-3=-66, -2=-44, -1=-22, 0=0, 1=22, 2=44, 3=66"],
        ["점령선 시작", 0, "중앙에서 시작"],
        ["점령선 이동", "가장 앞선 유닛이 새 구간에 들어가면 즉시 해당 구간으로 이동"],
        ["완전 점령", "raw sector > 3 또는 raw sector < -3", "3구간에 닿는 것이 아니라 3구간을 넘어 4구간 방향으로 가야 조기 종료"],
        ["라즈베리 스폰 위치", "sector_center(clamp(control, -3, 0)) - 4", "라즈베리는 왼쪽에서 오른쪽으로 이동"],
        ["블루베리 스폰 위치", "sector_center(clamp(control, 0, 3)) + 4", "블루베리는 오른쪽에서 왼쪽으로 이동"],
    ]
    rows.append([])
    rows.append(["구간", "중심 좌표"])
    for sector in range(-3, 4):
        rows.append([sector, sector * 22])
    return rows


def rows_victory() -> list[list[object]]:
    return [
        ["항목", "값", "설명"],
        ["라운드 제한 시간", "180초", "3분"],
        ["매치 승리 조건", "2라운드 선승", "최대 3라운드"],
        ["조기 종료", "한쪽이 모든 구간을 완전히 밀면 즉시 종료", "raw sector가 3을 초과하거나 -3 미만"],
        ["시간 종료 시 판정 1", "점령선이 양수면 라즈베리 승리", "라즈베리가 오른쪽으로 더 밀었음을 의미"],
        ["시간 종료 시 판정 2", "점령선이 음수면 블루베리 승리", "블루베리가 왼쪽으로 더 밀었음을 의미"],
        ["시간 종료 시 판정 3", "점령선이 0이면 생존 유닛 총 체력 비교", "총 체력이 같으면 랜덤"],
    ]


def rows_economy() -> list[list[object]]:
    return [
        ["항목", "값", "설명"],
        ["기본 크레딧", 500, "라운드 시작 시 지급"],
        ["수입 주기", "10초마다", "시뮬레이터 기준 10, 20, ..., 170초에 지급"],
        ["수입량", 500, "양 팀 동일"],
        ["180초 완주 시 기본 지급 총량", 9000, "초기 500 + 17회 수입 8500. 처치 보상 제외"],
        ["처치 보상", 50, "적 유닛 처치 시 공격한 팀에 지급"],
        ["업그레이드 비용", 1000, "공격 업그레이드와 체력 업그레이드 모두 동일"],
        ["업그레이드 최대 레벨", "제한 없음", "코드상 무제한 누적"],
        ["공격 업그레이드", "레벨당 기본 공격력/힐량 +30%", "모든 팀이 구매 가능"],
        ["체력 업그레이드", "레벨당 기본 체력 +30%", "모든 팀이 구매 가능"],
        ["기존 유닛 적용", "즉시 적용", "체력 업그레이드는 현재 체력 비율을 유지하며 최대 체력을 갱신"],
        ["라운드 간 유지", "업그레이드 유지, 크레딧 리셋", "매치 내 다음 라운드에도 업그레이드 레벨 유지"],
    ]


UNITS = [
    ["raspberry", "파이", "pie", "attacker", 80, 130, 0.8, 40, 1.0, 1.0, 0.0, "attack", "기본 근접 공격 유닛"],
    ["raspberry", "타르트", "tart", "aoe_ranged", 280, 250, 0.6, 20, 2.0, 6.0, 1.2, "attack", "긴 사거리 범위 원거리"],
    ["raspberry", "바움쿠헨", "baumkuchen", "tank", 250, 420, 0.8, 10, 1.8, 0.5, 0.0, "attack", "높은 체력의 탱커"],
    ["raspberry", "스콘", "scone", "single_ranged", 500, 300, 0.5, 100, 1.8, 3.0, 0.0, "attack", "강한 단일 원거리"],
    ["raspberry", "마카롱", "macaron", "special", 300, 50, 1.2, 50, 1.5, 2.5, 1.0, "heal", "아군을 회복하는 특수 유닛. 공격 업그레이드로 힐량 증가"],
    ["blueberry", "파이", "pie", "attacker", 100, 100, 1.0, 70, 1.0, 1.0, 0.0, "attack", "블루베리 기본 공격 유닛"],
    ["blueberry", "타르트타탱", "tarte_tatin", "aoe_ranged", 180, 180, 1.0, 50, 3.0, 4.0, 2.5, "attack", "강한 범위 원거리"],
    ["blueberry", "바움쿠헨", "baumkuchen", "tank", 250, 300, 1.0, 30, 1.0, 0.5, 0.0, "attack", "블루베리 탱커"],
    ["blueberry", "스콘", "scone", "single_ranged", 500, 200, 0.8, 150, 2.0, 3.0, 0.0, "attack", "강한 단일 원거리"],
    ["blueberry", "판나코타", "pannacotta", "special", 400, 50, 1.5, 400, 0.5, 1.0, 6.5, "suicide_aoe", "빠르게 돌진해 범위 자폭"],
]


def rows_units() -> list[list[object]]:
    rows = [
        [
            "team",
            "unit_name",
            "unit_key",
            "role",
            "cost",
            "hp",
            "speed",
            "power",
            "cooldown",
            "range",
            "area",
            "behavior",
            "effective_range",
            "effective_area",
            "sector_cross_time",
            "notes",
        ]
    ]
    for team, name, key, role, cost, hp, speed, power, cooldown, range_, area, behavior, notes in UNITS:
        rows.append([
            team,
            name,
            key,
            role,
            cost,
            hp,
            speed,
            power,
            cooldown,
            range_,
            area,
            behavior,
            round(range_ * 22.0 / 10.0, 3),
            round(area * 22.0 / 10.0, 3),
            round(22.0 / speed, 3) if speed else "",
            notes,
        ])
    return rows


def rows_combat() -> list[list[object]]:
    return [
        ["항목", "내용"],
        ["이동 속도", "Unity 기준 speed * Time.deltaTime과 동일하게 speed * dt로 적용"],
        ["시뮬레이션 dt", "0.5초"],
        ["사거리/범위 변환", "range 또는 area * SECTOR_WIDTH / 10"],
        ["타겟 선정", "진행 방향 앞쪽의 가장 가까운 적을 우선 공격. 없으면 가장 가까운 적"],
        ["공격 쿨다운", "cooldown_left가 0일 때 공격 가능. 공격 후 유닛별 cooldown 적용"],
        ["범위 공격", "목표 위치 주변 area 반경 안의 모든 적에게 피해"],
        ["단일 공격", "선택된 목표 1개에게 피해"],
        ["힐러", "사거리 안의 체력 비율이 가장 낮은 아군을 회복"],
        ["자폭 범위", "목표 주변 area 안의 적에게 피해를 준 뒤 자신은 사망"],
        ["집중 공격", "여러 유닛이 같은 목표를 공격할 수 있음. 단일 공격을 받는 쪽은 실제로 선택된 한 유닛이 피해를 받음"],
        ["사망 처리", "hp <= 0이면 사망, 처치 보상 50 지급"],
    ]


def rows_mcts() -> list[list[object]]:
    return [
        ["항목", "값", "설명"],
        ["주요 실험 에이전트", "UCT-backprop MCTS agent", "코드명 policy_train"],
        ["초기 정책 생성", "playouts 수만큼 매치 실행", "예: 5000 playout"],
        ["행동 후보", "wait, spawn:unit, upgrade:attack, upgrade:hp", "현재 크레딧으로 가능한 행동만"],
        ["상태 키", "시간 구간, 점령선, 크레딧 구간, 상대 크레딧 구간, 병력 압박, 총 업그레이드 차이, 공격 업그레이드 차이, 체력 업그레이드 차이"],
        ["선택 방식", "UCT", "평균 보상 + C * sqrt(log(total visits + 1) / visits)"],
        ["탐색 계수", 1.2, "PolicyMCTSAgent 기준"],
        ["랜덤 탐색", "12%", "학습 모드에서 일부 랜덤 행동 선택"],
        ["의사결정 주기", "1.2초", "PolicyMCTSAgent 기준"],
        ["매치 종료 업데이트", "역전파", "매치에서 선택한 상태-행동 경로를 거꾸로 갱신"],
        ["할인율", 0.995, "terminal에 가까운 행동의 보상을 더 강하게 반영"],
        ["최종 보상 구성", "매치 승리 60%, 라운드 승률 25%, 라운드 상태 평가 15%", ""],
        ["상태 평가 구성", "승패 50%, 점령선 28%, 체력 비율 14%, 업그레이드 우위 8%", ""],
        ["trained_mcts", "고정 정책 greedy 사용", "실행 중 역전파 업데이트 없음. 현재 연구 설명에는 policy_train 쪽이 더 적합"],
    ]


def rows_balance() -> list[list[object]]:
    return [
        ["항목", "내용"],
        ["연구 목적", "승률만 맞추는 하향 평준화를 피하고, 저기여 유닛을 살리면서 전체 밸런스를 맞추는 것"],
        ["현재 패치 후보 생성 방식", "우세 팀의 최고 기여 유닛을 소폭 너프 + 열세 팀의 저기여 유닛 전체 재조정"],
        ["기여도 지표", "피해량, 힐량, 받은 피해량, 킬, 생산량, 생존 시간, 집중공격 기여를 조합"],
        ["재조정 대상", "열세 팀에서 기여도가 낮은 유닛 1~2개"],
        ["재조정 스탯", "cost, hp, speed, cooldown, power, range, area"],
        ["재조정 profile", "balanced, offense, tempo"],
        ["후보 평가", "각 후보 패치를 적용하고 정책 복사본으로 평가 매치를 돌린 뒤 balance_score가 가장 낮은 후보 선택"],
        ["balance_score", "abs(raspberry_win_rate - 0.5) + control_weight * abs(avg_final_control)/3"],
        ["중요 주의", "2026-06-01 업그레이드 규칙 수정 후에는 기존 학습 결과를 재사용하지 말고 재학습해야 함"],
    ]


def rows_system_terms() -> list[list[object]]:
    return [
        ["시스템 용어", "이 프로젝트에서의 의미"],
        ["개체", "팀, 유닛, 라운드, 매치, 점령선, 업그레이드, 크레딧"],
        ["속성", "유닛의 cost, hp, speed, power, cooldown, range, area, behavior 등"],
        ["상태변수", "현재 시간, 점령선 위치, 각 팀 크레딧, 공격/체력 업그레이드 레벨, 생존 유닛 목록"],
        ["상태", "특정 시점의 전체 게임 상황. 예: 80초, 점령선 -1, 라즈베리 크레딧 500, 블루베리 유닛 12개"],
        ["사건", "수입 지급, 유닛 생산, 업그레이드 구매, 공격, 회복, 사망, 점령선 이동, 라운드 종료"],
        ["활동", "유닛 이동, 교전, 전선 밀기, MCTS 의사결정, 밸런스 후보 평가"],
    ]


def rows_files() -> list[list[object]]:
    return [
        ["파일/폴더", "내용"],
        ["raspberry_blue_sim/config.py", "맵, 경제, 업그레이드, 기본 유닛 스탯"],
        ["raspberry_blue_sim/simulator.py", "라운드/매치 시뮬레이션, 전투, MCTS 에이전트, 역전파 업데이트"],
        ["raspberry_blue_sim/iterative_balance_train.py", "반복 밸런스 학습, 후보 패치 생성/평가"],
        ["raspberry_blue_sim/run_experiment.py", "일반 실험 실행 및 CSV/JSON 결과 출력"],
        ["raspberry_blue_sim/render_replay.py", "1라운드 리플레이 JSON/GIF 생성"],
        ["raspberry_blue_sim/replays/", "발표용 리플레이 GIF/JSON"],
        ["raspberry_blue_sim/iterative_balance_runs_rework_v1_5000p/", "업그레이드 수정 전 규칙으로 돌린 최근 rework 실험 결과. 참고용"],
    ]


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_names = list(sheets)
    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml(sheet_names))
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("xl/workbook.xml", workbook_xml(sheet_names))
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(sheet_names))
        zf.writestr("xl/styles.xml", STYLES)
        for index, name in enumerate(sheet_names, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(sheets[name]))


def main() -> None:
    sheets = {
        "한눈에보기": rows_overview(),
        "기본규칙": rows_rules(),
        "맵": rows_map(),
        "승리조건": rows_victory(),
        "경제_업그레이드": rows_economy(),
        "유닛스탯": rows_units(),
        "전투규칙": rows_combat(),
        "MCTS_AI": rows_mcts(),
        "밸런스방식": rows_balance(),
        "시스템용어": rows_system_terms(),
        "프로젝트파일": rows_files(),
    }
    write_xlsx(OUT, sheets)
    print(OUT.resolve())


if __name__ == "__main__":
    main()
