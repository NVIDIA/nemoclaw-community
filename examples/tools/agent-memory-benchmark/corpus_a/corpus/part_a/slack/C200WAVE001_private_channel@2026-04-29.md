---
doc_id: S:C200WAVE001_private_channel@2026-04-29
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-04-29
message_count: 3
---

# #wave-ingest-design — 2026-04-29

[2026-04-29T13:33:05Z] Jordan Kim (U200DC075DFC) [ts=1777469585.420125]: question — current K-fanout on atlas is fixed at 8. is there a reason we don't tune it per workspace size? for tiny workspaces K=8 burns budget that yields no parallel speedup
[2026-04-29T13:47:33Z] Rohan Dasgupta (U200F6FF520A) [ts=1777470453.420125] (thread reply to 1777469585.420125): short answer: historical. we picked 8 because of a single benchmark on a medium workspace. nobody's gone back and re-tuned. would totally support a per-workspace K
[2026-04-29T14:03:58Z] Rohan Dasgupta (U200F6FF520A) [ts=1777471438.420125] (thread reply to 1777469585.420125): beacon would adopt whatever shape you land on — we're effectively in the same boat with our fanout knob
