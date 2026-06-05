# 5x6 Strategy Matrix Best Mid-Run Presentation Package

## Baseline vs Independent Validation
- Selected baseline: `raspberry_blue_sim/live_matrix_balance_loop_current/iteration_02`
- Balance source for validation: `raspberry_blue_sim/iteration10_continue_base_20260604_181127.json`
- Validation source: `raspberry_blue_sim/live_matrix_validation_current`
- Validation setup: iterations 1, matches 200, seed 11873, no additional patch loop
- Matrix size: 5 Raspberry strategies x 6 Blueberry strategies = 30 matchups

| Metric | Baseline | Validation | Delta |
|---|---:|---:|---:|
| Score | 0.359324 | 0.378023 | +0.018699 |
| Raspberry avg win rate | 0.462000 | 0.463700 | +0.001700 |
| Strategy spread | 0.471700 | 0.491200 | +0.019500 |
| Mirror gap | 0.340000 | 0.362000 | +0.022000 |
| Extreme rate | 0.366700 | 0.400000 | +0.033300 |
| Control gap | 0.611700 | 0.615100 | +0.003400 |

## Decision
The selected mid-run baseline remains a strong presentation candidate, but independent validation is slightly weaker. Baseline score was 0.359324; validation score was 0.378023, a delta of +0.018699. Raspberry average win rate stayed close: 46.20% baseline and 46.37% validation.

## Key Story
- The best mid-run point was found at continuation iteration 2, not at the final iteration.
- This point had the lowest score and lowest strategy spread among the compared runs.
- Independent validation reproduced the same broad balance pattern, though the exact score rose by about 0.0187.
- Remaining imbalance is still concentrated in weak `swarm_focus` pockets and strong Blueberry `suicide_aoe_focus` / `mixed` / `upgrade_focus` regions.

## Generated Assets
- `baseline_iteration02_matrix_5x6_heatmap.png`
- `validation_matrix_5x6_heatmap.png`
- `baseline_vs_validation_strategy_average.png`
- `loop_trend_with_selected_iteration.png`
- `baseline_vs_validation_metrics.csv`
- `strategy_average_baseline_vs_validation.csv`
