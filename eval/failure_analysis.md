# Failure analysis: strategy D (RAG + self-correction), qwen2.5-coder:3b

Every question D got wrong was inspected by hand (`python -m eval.inspect --failed`).

## Scorer fixes found during the audit

Q08 and Q12 were scored wrong but were correct: the model rounded to a different number of
decimals than the gold query (`-8.0` vs `-8.03`). The comparator now compares numbers at the
coarser of the two precisions, so `-8.03` matches `-8.0` while `0.45` still differs from `0.48`.
The old rule also allowed a 0.1% relative difference, which on GMV (R$15.7M) hid a R$2,140 error:
N01 was scored correct but was wrong. Tolerance now follows each value's stated precision, not its
magnitude. Results were rescored with `python -m eval.rescore` (no LLM calls): Q08 and Q12 became
correct, N01 became wrong.

## Breakdown of the remaining 27 failures

| Failure type | Count | Share | Questions |
|---|---|---|---|
| Wrong status filter | 6 | 22% | over-applied: Q01, Q04, Q06, N11; incomplete: N01, N18 |
| Wrong aggregation or grain | 6 | 22% | Q07, N04, N05, N19, Q16, Q20 |
| SQL error not fixed by retry | 4 | 15% | Q05, Q17, Q19, N15 |
| Wrong grouping or missing top-per-group | 3 | 11% | Q21, N13, Q18 |
| Glossary contamination (copied an unrelated date window) | 2 | 7% | N14, Q10 |
| Misread the question (wrong metric or sort direction) | 2 | 7% | N10, N16 |
| Ambiguous question / definition mismatch | 2 | 7% | Q09, N12 |
| Wrong table (misused a summary table) | 1 | 4% | Q15 |
| Correct rows, missing a requested column | 1 | 4% | Q14 |

Grouped into themes:

| Theme | Share | What it means |
|---|---|---|
| Reasoning and query structure | 44% (12) | Model capacity: aggregation grain, grouping, reading the question |
| Business-rule side effects | 30% (8) | Status filter over-applied or incomplete; unrelated date windows copied |
| Schema errors the retry loop couldn't fix | 15% (4) | Wrong column or join path, repeated despite repair hints |
| Benchmark ambiguity | 11% (3) | The question or gold answer allows another reasonable reading |

## Notable cases

- **Over-applied filter (Q01, Q04, Q06):** simple questions like "orders per status" got
  `WHERE order_status NOT IN ('canceled','unavailable')` copied from the retrieved "Valid order"
  rule. This is why RAG broke easy questions that schema-only answered correctly.
- **Incomplete filter (N01, N18):** used `<> 'canceled'`, keeping `unavailable` orders. GMV came out
  R$2,140 too high (15,737,667.52 vs 15,735,527.03). Five ground-truth examples used this older
  definition when the eval ran, so the few-shot examples taught it; they have since been standardized.
- **Glossary contamination (N14):** "Which month had the most orders?" got a "last 90 days"
  filter copied from the Active customer / recent-dates term, and grouped by day.
- **Missing outer aggregate (Q07, N04):** both returned one row per customer (`GROUP BY ... HAVING`)
  instead of wrapping it in a count. Same mistake, two questions.
- **Wrong grain (N19):** computed the multi-item share over item rows instead of orders (12.41% vs 9.94%).
- **Retry limits (Q19, N15):** Q19 kept selecting `customer_unique_id` from `orders` without joining
  `customers`; N15 kept hitting `ROUND(double precision)` even with the repair hint. Retry fixes
  errors when the fix is local, not when the query needs restructuring.
- **Benchmark ambiguity (Q09):** the glossary defines payment share by value, but the gold query
  counts payments. The model followed the glossary. Gold and glossary must agree.
- **Definition mismatch (N12):** counted `order_status = 'delivered'` (7069) instead of orders with a
  delivery date (7072). Defensible, but different from the funnel definition.

## What this suggests

1. Business rules should be retrieved only when the question uses the business term (e.g. revenue,
   customers), not attached to every question about orders. This targets the 27% theme and the
   easy-question regressions.
2. Retry helps with local errors only. Semantic mistakes (wrong grain, wrong grouping) produce valid
   SQL and need a different signal, such as a result sanity check or a larger model.
3. Gold answers and the glossary must share one definition per term (fixed: revenue; open: payment share).