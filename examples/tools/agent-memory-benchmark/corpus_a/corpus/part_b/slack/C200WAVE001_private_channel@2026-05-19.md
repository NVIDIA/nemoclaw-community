---
doc_id: S:C200WAVE001_private_channel@2026-05-19
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-19
message_count: 10
---

# #wave-ingest-design — 2026-05-19

[2026-05-19T08:51:07Z] Alex Chen (U200AC3F7E12) [ts=1779180667.621641]: separate question for this channel — selective context inclusion. is the "top-K relevant docs" filter the same as the embedding-rank approach beacon uses for chat? or different signal?
[2026-05-19T11:34:52Z] Alex Chen (U200AC3F7E12) [ts=1779190492.071612]: (asking because if it's the same signal we can share the rank cache. if it's different we shouldn't)
[2026-05-19T11:39:00Z] Rohan Dasgupta (U200F6FF520A) [ts=1779190740.071612] (thread reply to 1779190492.071612): (also we should probably promote that cache to a shared service eventually — both projects re-rank the same docs)
[2026-05-19T11:45:59Z] Rohan Dasgupta (U200F6FF520A) [ts=1779191159.071612] (thread reply to 1779190492.071612): same signal. embedding-rank with a recency bias. we have a tiny in-memory cache keyed on (workspace_id, query_hash). I'll send you the code
[2026-05-19T13:15:31Z] Alex Chen (U200AC3F7E12) [ts=1779196531.050445]: +1 to promoting the rank cache to a shared service. let's not do it this quarter though — too much else in flight. file as Q3 work?
[2026-05-19T16:29:50Z] Morgan Lee (U200B3C81BDF) [ts=1779208190.447298]: let's frame the shared rank cache as a Q3 "platform-level" win and use it to justify a deeper Atlas/Beacon convergence at the off-site
[2026-05-19T16:49:55Z] Jordan Kim (U200DC075DFC) [ts=1779209395.447298] (thread reply to 1779208190.447298): +1 to the convergence framing. easier to sell as "shared platform investment" than two separate caches
[2026-05-19T16:54:23Z] Alex Chen (U200AC3F7E12) [ts=1779209663.447298] (thread reply to 1779208190.447298): (this is also a good off-site agenda item — the kind of thing that's hard to land in async)
[2026-05-19T16:55:54Z] Alex Chen (U200AC3F7E12) [ts=1779209754.447298] (thread reply to 1779208190.447298): agreed. I'll write a 1-pager on what "atlas + beacon shared runtime convergence" looks like in concrete terms. nothing fancy
[2026-05-19T18:01:50Z] Jordan Kim (U200DC075DFC) [ts=1779213710.447298] (thread reply to 1779208190.447298): noting for the off-site: would love to also talk about how we share evaluation harnesses between atlas and beacon. anya and I have been duplicating effort
