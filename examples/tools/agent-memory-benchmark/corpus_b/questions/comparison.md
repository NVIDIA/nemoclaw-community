# Comparison over 98 shared questions

Both systems graded on exactly the questions both answered.

| type | count |
|---|---:|
| abstention | 12 |
| as_of | 7 |
| chain_freshness | 2 |
| disambiguation | 8 |
| freshness | 7 |
| multi_source | 21 |
| ordering | 1 |
| single_hop | 40 |

| metric | cos_b_all | agentic_rag_b_all | naive_rag_b_all |
|---|---|---|---|
| accuracy | 0.8163 | 0.7959 | 0.7857 |
| abstention | 0.6667 | 0.6667 | 0.5833 |
| as_of | 1.0 | 1.0 | 1.0 |
| chain_freshness | 0.5 | 0.0 | 0.0 |
| disambiguation | 0.875 | 0.875 | 0.875 |
| freshness | 0.7143 | 0.7143 | 0.7143 |
| multi_source | 0.7619 | 0.7619 | 0.7619 |
| ordering | 1.0 | 1.0 | 1.0 |
| single_hop | 0.875 | 0.85 | 0.85 |
| evidence recall | 0.8525 | 0.9016 | 0.9016 |
| citation coverage | 0.9898 | 0.9898 | 0.9898 |
