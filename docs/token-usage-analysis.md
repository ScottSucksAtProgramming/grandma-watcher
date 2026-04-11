# Token Usage Analysis — NanoGPT / Qwen3 VL 235B A22B Instruct

**Date:** 2026-04-11
**Sample:** 20 consecutive API calls from NanoGPT dashboard

## Per-Prompt Token Profile

| Metric | Value |
|---|---|
| Input tokens | 1143 (constant — fixed prompt + image encoding) |
| Output tokens | 59.2 avg (range: 51–66, very stable) |
| **Total per prompt** | **~1,202 tokens** |

Input tokens are deterministic at 1143 every call. Output variance is minimal (±8 tokens), making this a reliable baseline for cross-model cost estimation.

## Daily / Weekly Usage Projections

| Interval | Prompts/Day | Tokens/Day | Tokens/Week | % of 60M NanoGPT limit |
|---|---|---|---|---|
| 20 sec | 4,320 | 5,193,504 | 36,354,528 | 61% |
| 30 sec | 2,880 | 3,462,336 | 24,236,352 | 40% |
| 60 sec | 1,440 | 1,731,168 | 12,118,176 | 20% |
| 120 sec | 720 | 865,584 | 6,059,088 | 10% |

Current config runs at **30s → ~24M tokens/week (40% of weekly limit)**.
All four intervals stay comfortably under the 60M/week NanoGPT cap.

## Cross-Model Cost Formula

To estimate cost on any model, multiply:

```
cost = (1143 × input_rate) + (59.2 × output_rate)
```

where rates are in $/token (i.e. $/1M tokens ÷ 1,000,000).

Then multiply by prompts/day for daily cost.

## Raw Sample Data

| Timestamp | Input Tokens | Output Tokens | Total |
|---|---|---|---|
| 4/11/2026, 1:08:54 PM | 1143 | 56 | 1199 |
| 4/11/2026, 1:08:22 PM | 1143 | 56 | 1199 |
| 4/11/2026, 1:07:47 PM | 1143 | 62 | 1205 |
| 4/11/2026, 1:07:14 PM | 1143 | 56 | 1199 |
| 4/11/2026, 1:06:39 PM | 1143 | 62 | 1205 |
| 4/11/2026, 1:06:07 PM | 1143 | 66 | 1209 |
| 4/11/2026, 1:05:30 PM | 1143 | 66 | 1209 |
| 4/11/2026, 1:04:56 PM | 1143 | 62 | 1205 |
| 4/11/2026, 1:04:21 PM | 1143 | 61 | 1204 |
| 4/11/2026, 1:03:49 PM | 1143 | 60 | 1203 |
| 4/11/2026, 1:03:14 PM | 1143 | 62 | 1205 |
| 4/11/2026, 1:02:42 PM | 1143 | 61 | 1204 |
| 4/11/2026, 1:02:09 PM | 1143 | 56 | 1199 |
| 4/11/2026, 1:01:32 PM | 1143 | 51 | 1194 |
| 4/11/2026, 1:00:59 PM | 1143 | 62 | 1205 |
| 4/11/2026, 1:00:26 PM | 1143 | 51 | 1194 |
| 4/11/2026, 12:59:54 PM | 1143 | 60 | 1203 |
| 4/11/2026, 12:59:18 PM | 1143 | 62 | 1205 |
| 4/11/2026, 12:58:45 PM | 1143 | 56 | 1199 |
| 4/11/2026, 12:58:12 PM | 1143 | 56 | 1199 |
