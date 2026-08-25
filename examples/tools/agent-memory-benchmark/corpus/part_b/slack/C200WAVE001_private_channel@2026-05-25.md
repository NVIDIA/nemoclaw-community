---
doc_id: S:C200WAVE001_private_channel@2026-05-25
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-25
message_count: 2
---

# #wave-ingest-design — 2026-05-25

[2026-05-25T11:31:12Z] Jordan Kim (U200DC075DFC) [ts=1779708672.600593]: one thought re shared runtime — if we're going to copy code in the short term, let's at least co-locate the duplicated bits in a single file with a comment so future-us knows where to look when we deduplicate
[2026-05-25T12:32:07Z] Rohan Dasgupta (U200F6FF520A) [ts=1779712327.409145]: +1 jordan. I'll put a `_shared_runtime_candidates.py` file on the beacon side with a clear "TODO: extract to shared package" comment
