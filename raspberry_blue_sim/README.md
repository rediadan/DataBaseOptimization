# Raspberry Blue Balance Simulator

라즈베리블루 기말 발표용 밸런스 실험 시뮬레이터 v0입니다.

## 실행

```powershell
python raspberry_blue_sim/run_experiment.py --matches 200 --seed 42 --out raspberry_blue_sim/out
```

MCTS 에이전트를 사용하려면:

```powershell
python raspberry_blue_sim/run_experiment.py --matches 30 --seed 42 --agent mcts --out raspberry_blue_sim/out_mcts
```

플레이아웃으로 정책을 학습하려면:

```powershell
python raspberry_blue_sim/train_mcts.py --playouts 200 --seed 42 --policy-out raspberry_blue_sim/policies/mcts_policy.json
```

학습된 정책으로 평가하려면:

```powershell
python raspberry_blue_sim/run_experiment.py --matches 100 --seed 43 --agent trained_mcts --policy raspberry_blue_sim/policies/mcts_policy.json --out raspberry_blue_sim/out_trained_mcts
```

자동 밸런싱을 실행하려면:

```powershell
python raspberry_blue_sim/optimize_balance.py --iterations 3 --matches 20 --seed 100 --agent trained_mcts --policy raspberry_blue_sim/policies/mcts_policy.json --out raspberry_blue_sim/balance_out
```

조정 전/후 분석 결과와 그래프를 만들려면:

```powershell
python raspberry_blue_sim/run_experiment.py --matches 100 --seed 43 --agent trained_mcts --policy raspberry_blue_sim/policies/mcts_policy.json --out raspberry_blue_sim/analysis_before
python raspberry_blue_sim/run_experiment.py --matches 100 --seed 43 --agent trained_mcts --policy raspberry_blue_sim/policies/mcts_policy.json --balance-result raspberry_blue_sim/balance_out/balance_result.json --out raspberry_blue_sim/analysis_after
python raspberry_blue_sim/compare_results.py --before raspberry_blue_sim/analysis_before --after raspberry_blue_sim/analysis_after --out raspberry_blue_sim/analysis_compare
python raspberry_blue_sim/plot_results.py --compare raspberry_blue_sim/analysis_compare --history raspberry_blue_sim/balance_out/balance_history.csv --out raspberry_blue_sim/analysis_graphs
```

## 현재 모델

- 1D 실시간 전략 물량전
- 7구간 점령: `-3, -2, -1, 0, 1, 2, 3`
- 라운드 180초, 3판 2선승
- 시작 크레딧 500, 10초마다 500 지급, 처치 보상 50
- 버튼 즉시 생산
- 라운드가 끝나도 업그레이드 레벨 유지
- 라즈베리: 공격력 업그레이드
- 블루베리: 체력 업그레이드
- AI 선택 가능: `heuristic`, `mcts`, `trained_mcts`

## MCTS 에이전트

현재 MCTS 에이전트는 매 의사결정마다 가능한 행동을 만듭니다.

- 대기
- 업그레이드
- 생산 가능한 유닛 즉시 생산

각 행동은 UCT로 선택되고, 짧은 미래 시뮬레이션을 반복 실행해 보상값을 추정합니다. 보상은 승패 예측, 점령선 위치, 남은 체력 비율, 업그레이드 우위를 함께 사용합니다.

## 플레이아웃 학습

`train_mcts.py`는 반복 플레이아웃을 실행하면서 상태-행동별 방문 수, 누적 보상, 승리 수를 정책 파일에 저장합니다.

상태는 점령선, 시간 구간, 크레딧 구간, 병력 수 차이, 업그레이드 차이를 압축해서 기록합니다. `trained_mcts`는 저장된 정책에서 현재 상태의 평균 보상이 가장 높은 행동을 선택합니다.

## 자동 밸런싱

`optimize_balance.py`는 현재 우세한 팀을 찾고, 유닛별 생산량/처치/피해량/회복량을 바탕으로 기여도가 높은 유닛을 추립니다. 이후 공격력, 체력, 속도, 비용, 범위 후보 패치를 만들어 실제 매치 평가로 가장 목표 승률에 가까운 조정을 채택합니다.

결과는 `balance_result.json`과 `balance_history.csv`에 저장됩니다.

## 출력

- `matches.csv`: 매치 단위 결과
- `rounds.csv`: 라운드 단위 결과
- `unit_stats.csv`: 매치별 유닛 생산/처치/피해/회복 통계
- `summary.json`: 전체 승률과 요약 지표

`unit_stats.csv`에는 매치당 생산량, 팀 내 생산 비율, 피해량, 생존 시간, 공격 횟수, 집중공격 관련 지표도 함께 저장됩니다.
