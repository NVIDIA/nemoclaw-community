---
doc_id: S:C200WAVE001_private_channel@2026-05-24
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-24
message_count: 4
---

# #wave-ingest-design — 2026-05-24

[2026-05-24T10:31:24Z] Jordan Kim (U200DC075DFC) [ts=1779618684.034156]: one risk I want to surface — when prefix-trim is on AND big-doc split is on AND K is small, we have three knobs interacting. have we tested that combination on a real workspace?
[2026-05-24T10:49:38Z] Alex Chen (U200AC3F7E12) [ts=1779619778.034156] (thread reply to 1779618684.034156): not yet — only tested pairwise. I'll add the all-on combo to my test workspace today and let it run for 24h. will report back tomorrow
[2026-05-24T10:54:32Z] Morgan Lee (U200B3C81BDF) [ts=1779620072.034156] (thread reply to 1779618684.034156): good catch. let's add a smoke test for the all-on combination before we declare it shippable
[2026-05-24T15:50:53Z] Rohan Dasgupta (U200F6FF520A) [ts=1779637853.266742]: beacon side: I'm going to mirror your big-doc-split logic in our wave_planner equivalent. fine to copy the code? simpler than building shared utility right now
