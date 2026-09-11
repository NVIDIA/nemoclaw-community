---
name: vss-video
description: Use when a question is about what happens in a video file or clip. Puts the clip in front of NVIDIA RT-VLM and reports timestamped, grounded findings.
version: 1.0.0
license: Apache-2.0
metadata:
  hermes:
    tags: [video, vision, vss, nvidia]
---

# Answering questions about a video

You have two tools. Both are plugin tools, so call them through `tool_call`:

```
tool_call(name="vss_describe_video", arguments={"video": "forklift-training.mp4", "focus": "safety hazards"})
tool_call(name="vss_ask_video",      arguments={"video": "forklift-training.mp4", "question": "How many people are on foot?"})
```

`video` is a filename or relative path for a file already beneath
`/sandbox/videos`. Never pass an `http(s)` URL, host path, or traversal path.
Anything else fails with a clear refusal; report that rather than guessing. A
host operator may add a reviewed clip with
`./swarm video-add PATH`; chat text and attachments do not upload host files.

## Order of work

1. **Describe first.** One `vss_describe_video` per clip per turn. It returns
   `[mm:ss-mm:ss]` lines. Read all of them before you form an opinion.
2. **Ask for specifics.** If the question needs a count, a colour, a yes/no on
   whether something happened, or who was where when, call `vss_ask_video` with
   one concrete question. Concrete means answerable by looking:
   "How many people wear hi-vis?" not "Is this safe?". One question per call;
   two or three calls is normal, ten is not.
3. **Report with timestamps.** Lead with the findings that answer the question,
   each pinned to a time range. Then anything else notable. Then what the
   footage does not show, if that matters to the asker.

## Prompt shapes that work

- `focus` on describe: a short noun phrase. "people near moving vehicles",
  "anyone entering through the side door", "damaged goods".
- `question` on ask: present tense, one thing, visible. "Does the forklift
  driver look at the pedestrian before turning?" "What colour is the pallet
  at 00:20?" "Is the exit door blocked at any point?"
- Avoid asking the model to judge ("is this a violation?"). Ask what is
  visible and judge it yourself, labelled as your inference.

## Limits

- Clips up to about 60 seconds and 40 MiB inline. Ask for a shorter cut when
  footage exceeds that cap; the tool's error tells you the size.
- The model reports what it sees. Small text, faces at distance, and events
  behind other objects are often "not visible". That is a finding, not a
  failure; report it as such.
- Timestamps are approximate to a second or two.

## When a teammate asks you

They cannot watch the clip. Give them the timestamped findings, quote the
model where the wording matters, and mark inference as inference. Answer in
the same turn. If the clip is not where they said, tell them what is there.
