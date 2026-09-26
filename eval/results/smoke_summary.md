# Eval results: `smoke`

2 questions. Execution match = the query's result equals the gold query's result (column names/order ignored, small rounding tolerance).

| Strategy | Execution match | Valid SQL | Exact SQL match | Avg attempts | Avg latency (s) | Avg tokens in |
|---|---|---|---|---|---|---|
| A: Baseline (question only) (2) | **0%** | 50% | 0% | 1.0 | 30 | 333 |
| B: Schema only (2) | **50%** | 50% | 0% | 1.0 | 28 | 800 |
| C: RAG (1 attempt) (2) | **50%** | 100% | 0% | 1.0 | 93 | 2077 |
| D: RAG + self-correction (2) | **50%** | 100% | 0% | 1.0 | 94 | 2077 |

## Execution match by difficulty

| Strategy | easy (n) | medium (n) | hard (n) |
|---|---|---|---|
| A: Baseline (question only) | 0% (2) | - (0) | - (0) |
| B: Schema only | 50% (2) | - (0) | - (0) |
| C: RAG (1 attempt) | 50% (2) | - (0) | - (0) |
| D: RAG + self-correction | 50% (2) | - (0) | - (0) |

## Execution match by category

| Category | A | B | C | D |
|---|---|---|---|---|
| ground_truth | 0% | 50% | 50% | 50% |

## Self-correction

- First-attempt SQL errors: 0; fixed by retry: 0 (-)
- Questions turned from wrong to correct by retry: 0 []

## RAG vs schema-only (B vs C)

- RAG fixed: 1 ['Q02']
- RAG broke: 1 ['Q01']
