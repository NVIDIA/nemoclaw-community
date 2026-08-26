# self-model — nvidia/nvidia/nemotron-3-ultra
> Measures a consolidating design that does not ship an adapter here; the row is a data point, not something this repository can re-run.


* corpus: 425 docs (212 part_a / 213 part_b)
* questions: 186 (graded deterministically: 186, deferred to judge: 0)

## Quality
* accuracy overall: **0.9086**
  * [base] 0.9032
  * [hard] 0.9355
  * abstention: 0.7692
  * as_of: 0.8333
  * attribution: 0.8
  * chain_freshness: 1.0
  * citation: 1.0
  * constraint: 1.0
  * disambiguation: 0.8667
  * freshness: 0.9167
  * multi_source: 0.9452
  * ordering: 1.0
  * set_difference: 1.0
  * single_hop: 0.8333
  * freshness with a competing stale claim in corpus: 0.8889
  * freshness recency-only: 1.0

## Evidence (diagnostic, not part of accuracy)
* citation coverage: 0.9785
* evidence recall: 0.4017
* evidence precision: 0.4598

## Cost
* ingest: 180119409 in / 2641300 out in 5960.74s
* answering: 44597597 in / 273057 out in 3137.42s
* per question: 241240.1 tokens
* accounting: proxy
* system's own counter (spans resumed segments the proxy did not supervise): 40,134,158 in / 2,914,357 out over 258 calls
