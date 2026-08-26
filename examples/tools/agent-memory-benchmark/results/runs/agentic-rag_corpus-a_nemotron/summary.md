# agentic-rag — nvidia/nvidia/nemotron-3-ultra

* corpus: 425 docs (212 part_a / 213 part_b)
* questions: 186 (graded deterministically: 186, deferred to judge: 0)

## Quality
* accuracy overall: **0.8441**
  * [base] 0.8645
  * [hard] 0.7419
  * abstention: 1.0
  * as_of: 0.5
  * attribution: 0.8
  * chain_freshness: 0.6
  * citation: 0.9167
  * constraint: 0.8
  * disambiguation: 0.6667
  * freshness: 0.75
  * multi_source: 0.8767
  * ordering: 0.75
  * set_difference: 1.0
  * single_hop: 0.9
  * freshness with a competing stale claim in corpus: 0.6667
  * freshness recency-only: 1.0

## Evidence (diagnostic, not part of accuracy)
* citation coverage: 0.9247
* evidence recall: 0.6342
* evidence precision: 0.7535

## Cost
* ingest: 169852 in / 0 out in 25.46s
* answering: 2472672 in / 226034 out in 358.54s
* per question: 14509.2 tokens
* accounting: proxy
* USD (price snapshot 2026-08-21): ingest $0.0034, answering $None
