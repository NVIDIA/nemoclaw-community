# Tech Radar

1. Add the **Tech Radar skill** to any personal agent in Hiring or Edit agent. The Tech Radar preset is a shortcut; the skill controls Heartbeat.
2. Connect the model. No upload or chat prompt is needed.
3. OpenClaw checks every **20 seconds** for an unread article from NVIDIA Developer Blog or Hugging Face Blog. A completed summary includes the source link.
4. Use **Pause / Resume** in the agent panel.

The first check cannot start during the first 10 seconds after hiring or changing the agent's skills. Runtime preparation or the native scheduler can delay it further. Suggested feed hosts do not produce policy alerts before an access request; actual denials appear when OpenShell blocks a request.

While this skill is equipped, manual chat, attachments and scheduled follow-ups are disabled, and Run all agents excludes the agent. This applies even with additional skills or while Heartbeat is paused. For a Tech Radar preset, choose another role before removing its fixed skill to restore manual chat.

Older feed entries are eligible: the agent discovers useful reading rather than waiting for newly published posts. Each short summary has a source link and publication date, and follows the chosen persona. The source evidence is the feed excerpt, not a full article review. Politics, investing, earnings and personnel announcements are excluded using a preliminary filter and agent judgment.

Shared URLs and skipped items are remembered in the agent workspace across restarts. The agent stays quiet when it exhausts the available relevant feed entries; it does not repeat old summaries or invent news. Feed changes are checked with conditional caching. Removing the agent removes its discovery history.

20 seconds is the native heartbeat cadence, not a response deadline. Model calls and ongoing tasks may delay an update. Checks pause while the model is disconnected, the agent is assigned other work, or its owning browser session is disconnected. Authenticated browser activity renews a 90-second lease, including for keyless local models. Closing the last tab ends its lease; a lost close signal expires within 90 seconds plus the relay check interval. Other browser sessions cannot keep this session’s agents running. Restart leaves all Radar timers disabled until their owner reconnects. Keep the app server, runtime and owning browser tab running. Pause stops future checks; an in-flight turn may finish, and its queued result appears after Resume.

With **OpenShell on**, approve `developer.nvidia.com` and `huggingface.co` in the agent's **OpenShell Policy** panel. The fixed feed requests run inside the sandbox; blocked requests are not retried through a host connection.

Entering **Open Task** temporarily pauses your hired agents' Heartbeats, even before Casey assigns work. Return to the Lounge in your active tab to resume the 20-second cadence, even with Open Task open in a background tab. Manually paused agents stay paused. An in-flight check may finish, and its saved result is imported after you leave.

## Waiting states

- **Waiting for model:** neither enabled connection is ready. Check Settings → Model.
- **Waiting for runtime:** OpenClaw is not ready.
- **Waiting for other agents:** the native request queue is busy with foreground work.
- **Retrying preparation:** runtime setup failed; retries back off for 15, 30, then up to 60 seconds.
- **Waiting for browser:** reopen the owning browser session.
- **Paused in Open Task:** leave Open Task to resume periodic checks.

Heartbeat follows the effective Hiring/Lounge connection, including a ready fallback or host-saved NVIDIA key. A changed route is prepared again before checks resume. Preparation is separate from article generation; a failed setup does not mark the agent ready or replay a submitted model request.

## arXiv researcher

Hiring also offers **arXiv researcher**: give it a topic and it searches for three relevant arXiv papers, summarizes the abstracts and compares the papers with titles, authors, dates and links. Its **Web research** skill is fixed; extra skills can be added. It has no periodic heartbeat. Tech Radar remains the recurring discovery preset with a fixed role and **Tech Radar** skill. Agents with Tech Radar are excluded from periodic Lounge chatter, even when Heartbeat is paused; actual updates remain visible.

## Who does what

- **OpenClaw** owns the per-agent 20-second timer and isolated model/tool execution. Other agents keep heartbeats disabled. Automatic Skill Workshop reviews are also disabled: demo skills are managed by the app, and those unrelated reviews can block the shared scheduler.
- **The agent** follows `HEARTBEAT.md` and `bac-radar/SKILL.md`, selects an unread article and writes a short summary in its persona.
- **The feed tool** fetches the two fixed HTTPS feeds, supplies excerpts, validates the selected source and records the model-authored text once. It never authors the summary.
- **The app** saves each new summary in the agent’s Lounge chat.

See [release notes](../RELEASE_NOTES.md) for the studio version.
