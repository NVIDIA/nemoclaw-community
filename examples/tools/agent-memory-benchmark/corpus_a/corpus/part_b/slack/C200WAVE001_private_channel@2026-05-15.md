---
doc_id: S:C200WAVE001_private_channel@2026-05-15
source: slack
channel_id: C200WAVE001
channel_name: wave-ingest-design
channel_type: private_channel
date: 2026-05-15
message_count: 3
---

# #wave-ingest-design — 2026-05-15

[2026-05-15T10:47:30Z] Morgan Lee (U200B3C81BDF) [ts=1778842050.131723]: the "split big docs into their own wave" framing is clean. let's lean that direction. <@U200AC3F7E12> can you update !335 to include that as the escape path?
[2026-05-15T16:00:28Z] Rohan Dasgupta (U200F6FF520A) [ts=1778860828.998015]: one more thing on selective context inclusion — beacon found that pruning the context window down to top-K relevant docs (rather than all-in-wave) saves ~22% tokens with no quality drop. worth porting to atlas?
[2026-05-15T17:00:13Z] Morgan Lee (U200B3C81BDF) [ts=1778864413.249373]: yes, worth it. let's scope a separate spec for that — keep !335 about K-fanout and merge budget; selective context is its own thing
