# Eval results: `v2_gated`

40 questions. Execution match = the query's result equals the gold query's result (column names/order ignored, small rounding tolerance).

| Strategy | Execution match | Valid SQL | Exact SQL match | Avg attempts | Avg latency (s) | Avg tokens in |
|---|---|---|---|---|---|---|
| A: Baseline (question only) (40) | **2%** | 18% | 2% | 1.0 | 29 | 335 |
| B: Schema only (40) | **25%** | 58% | 0% | 1.0 | 27 | 802 |
| C: RAG (1 attempt) (40) | **38%** | 82% | 2% | 1.0 | 132 | 2084 |
| D: RAG + self-correction (40) | **38%** | 85% | 2% | 1.4 | 154 | 2902 |

## Execution match by difficulty

| Strategy | easy (n) | medium (n) | hard (n) |
|---|---|---|---|
| A: Baseline (question only) | 8% (12) | 0% (19) | 0% (9) |
| B: Schema only | 75% (12) | 5% (19) | 0% (9) |
| C: RAG (1 attempt) | 50% (12) | 47% (19) | 0% (9) |
| D: RAG + self-correction | 50% (12) | 47% (19) | 0% (9) |

## Execution match by category

| Category | A | B | C | D |
|---|---|---|---|---|
| aggregation | 0% | 67% | 33% | 33% |
| glossary | 0% | 22% | 67% | 67% |
| glossary_trap | 100% | 100% | 100% | 100% |
| ground_truth | 0% | 25% | 30% | 30% |
| summary_table | 0% | 0% | 0% | 0% |
| time | 0% | 0% | 50% | 50% |

## Self-correction

- First-attempt SQL errors: 7; fixed by retry: 1 (14%)
- Questions turned from wrong to correct by retry: 0 []

## RAG vs schema-only (B vs C)

- RAG fixed: 10 ['N01', 'N03', 'N07', 'N09', 'N18', 'Q02', 'Q08', 'Q11', 'Q12', 'Q13']
- RAG broke: 5 ['N16', 'Q01', 'Q04', 'Q05', 'Q06']
