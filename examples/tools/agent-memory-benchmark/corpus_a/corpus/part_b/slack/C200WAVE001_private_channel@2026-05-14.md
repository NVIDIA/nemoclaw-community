---
doc_id: S:C200WAVE001_private_channel@2026-05-14
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-14
message_count: 2
---

# #wave-ingest-design — 2026-05-14

[2026-05-14T14:38:06Z] Rohan Dasgupta (U200F6FF520A) [ts=1778769486.763781]: read !335 — the math looks right, but the margin factor (1.4x) feels hand-wavy. what if a single doc is way over the average tokens? we'd hit the budget cap and degrade silently
[2026-05-14T18:08:28Z] Rohan Dasgupta (U200F6FF520A) [ts=1778782108.868618]: follow-up: maybe the right escape valve is "if any single doc exceeds budget/K, split it off as its own wave". not silent degradation, just adaptive shape
