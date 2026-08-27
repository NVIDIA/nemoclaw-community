---
doc_id: S:C200WAVE001_private_channel@2026-05-20
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-20
message_count: 3
---

# #wave-ingest-design — 2026-05-20

[2026-05-20T14:28:54Z] Rohan Dasgupta (U200F6FF520A) [ts=1779287334.817007]: K-curve sim results are interesting — the optimal K barely moves between 100 and 1000 docs (stays around 6-8). below 100 docs you really want K=2-4. above 1000 the curve flattens
[2026-05-20T18:16:08Z] Rohan Dasgupta (U200F6FF520A) [ts=1779300968.400052]: implication: the per-workspace K knob is mostly only worth it for small workspaces. the big-doc split is more impactful for larger ones
[2026-05-20T18:21:15Z] Jordan Kim (U200DC075DFC) [ts=1779301275.793743]: that simplifies the rollout — K=8 stays as default, override only fires when n_docs < 100. less surface area to test
